# Replay Vision logs: mirror pipeline logs to the Logs product via a structlog tap

## Problem

The Replay Vision "ship pipeline logs into the Logs product" bridge (code #71314, charts #13215)
is a silent no-op in production. It attaches a stdlib `logging.Handler` (`OtelLogHandler`) to the
stdlib logger `products.replay_vision.backend.temporal`. But the temporal worker calls
`structlog.reset_defaults()` and configures structlog with a custom non-stdlib `LoggerFactory`
(`posthog/temporal/common/logger.py`), so records never reach stdlib logging and the handler is
never invoked. No logs arrive under `service.name = replay-vision`. The failure is completely silent
(no export attempts, no errors). Unit tests missed it because they log through a stdlib logger
directly, never through the worker's real structlog config.

## Goal

Actually ship the Replay Vision temporal pipeline logs into the PostHog Logs product under
`service.name = replay-vision`, integrated with the worker's real structlog pipeline, fail-soft, and
with a test that runs through the real chain so this cannot regress silently. Keep the fail-closed
allowlist from the security review.

## Non-goals

- No change to how any other temporal worker logs.
- No change to the stdout-scraping path (pipeline logs remain queryable under
  `temporal-worker-replay-vision` regardless).
- No new call sites in Replay Vision activity/workflow code.

## Design

### 1. Generic OTLP structlog tap (`posthog/otel_logs.py`)

Add a structlog processor factory that mirrors matching records to OTLP and returns the event dict
unchanged (a side-effecting "tap", not a renderer). It reuses the existing lazy per-process provider,
severity mapping, and `LogRecord` emission already in this module, plus the same allowlist semantics
as `OtelLogHandler`.

- Signature: a factory `otel_log_mirror_processor(service_name, *, logger_prefix, attribute_allowlist)`
  returning a `(logger, method_name, event_dict) -> event_dict` callable.
- Body/attributes come from the structlog `event_dict` (not a stdlib `LogRecord`): body is the event
  message (`msg` or `event` key), attributes are the allowlisted scalar keys. Exceptions contribute
  only their type when an allowlist is set (never message or traceback).
- Fail-soft: wrapped in `try/except`, always returns `event_dict`, never logs (no recursion).
- Cheap early return when the record's logger name does not start with `logger_prefix`, or when the
  provider is disabled (OTLP env unset).
- Extract the shared "emit one record to OTLP" core so both `OtelLogHandler` and the tap use it (no
  duplicated provider/severity/LogRecord logic).

`OtelLogHandler` stays as a general-purpose stdlib handler for genuine stdlib-logging contexts. It is
simply no longer used by the Replay Vision worker path.

### 2. Insert the tap before the terminal renderer (`posthog/temporal/common/logger.py`)

`extra_processors` are appended after `LogMessagesRenderer` (the terminal renderer that returns
`{write_message, produce_message}`), so a tap there would receive rendered output, not the event dict.
Add one opt-in, backwards-compatible parameter to `configure_logger` that inserts a caller-supplied
processor immediately before the terminal renderer in both the prod and tty/test branches (so tests
exercise the real chain). Default `None` means no change for every existing caller.

### 3. Warm the provider at startup (Temporal sandbox safety)

The OTLP provider uses a `BatchLogRecordProcessor`, which spawns a background thread on creation.
Temporal forbids thread creation inside the workflow sandbox. `configure_logger` runs once at worker
startup (safe context), so warm the provider there (build it eagerly) so no thread is ever spawned
lazily during workflow execution. After warming, the tap's per-record path only enqueues.

### 4. Wire it for the Replay Vision queue (`start_temporal_worker.py`)

`handle()` already knows `task_queue` and already branches per queue. When
`task_queue == settings.REPLAY_VISION_TASK_QUEUE`, pass the tap (built from the Replay Vision config)
to `configure_logger`. The Replay Vision specifics live in `products/replay_vision`:
`VISION_LOGS_SERVICE_NAME = "replay-vision"`, prefix `products.replay_vision.backend.temporal`, and
the existing `VISION_LOG_ATTRIBUTE_ALLOWLIST`.

### 5. Cleanup

Remove the ineffective `install_vision_log_bridge()` stdlib-handler install and its call in
`products/replay_vision/backend/temporal/__init__.py`. Replace `logs.py` with the tap factory plus the
allowlist and service-name constants.

## Testing

- **Integration (the missing coverage):** configure the real worker logger via `configure_logger`
  with the Replay Vision tap and OTLP settings patched on, log through a
  `products.replay_vision.backend.temporal.*` logger, and assert one OTLP `LogRecord` was emitted with
  `service.name = replay-vision`, the correct body/severity, and only allowlisted attributes. Assert a
  payload-derived field (e.g. a `response_preview`) is dropped. This runs through the same chain prod
  uses, which is what would have caught the original bug.
- **Unit:** the tap's extraction and allowlist behavior, fail-soft on emit error, and the
  logger-prefix early return (a non-matching logger is not mirrored).
- **Guard:** with OTLP env unset, the tap is a no-op (no provider built).
- Remove or adapt obsolete `OtelLogHandler`-only tests that asserted the old bridge path.

## Backwards compatibility

Additive opt-in `configure_logger` param (default no-op), one task-queue-keyed branch in the start
command, product config staying in the product. No other worker changes behavior. The generic
`OtelLogHandler` is unchanged.

## Risks

- Touching the shared `configure_logger` (used by all temporal workers). Mitigated by the additive,
  default-`None` param and existing `configure_logger` tests staying green.
- Provider thread in workflow context. Mitigated by warming at startup (item 3).
- Over-shipping non-Replay-Vision logs. Mitigated by the `logger_prefix` scope in the tap.
