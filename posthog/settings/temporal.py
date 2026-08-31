import os

from posthog.settings.access import SECRET_KEY
from posthog.settings.base_variables import CLOUD_DEPLOYMENT, DEBUG
from posthog.settings.utils import get_from_env, get_list, str_to_bool

TEMPORAL_NAMESPACE: str = os.getenv("TEMPORAL_NAMESPACE", "default")
TEMPORAL_HOST: str = os.getenv("TEMPORAL_HOST", "temporal")
TEMPORAL_UI_HOST: str = os.getenv("TEMPORAL_UI_HOST", "http://localhost:8081" if DEBUG else "https://cloud.temporal.io")
TEMPORAL_PORT: str = os.getenv("TEMPORAL_PORT", "7233")
TEMPORAL_CLIENT_ROOT_CA: str | None = os.getenv("TEMPORAL_CLIENT_ROOT_CA", None)
TEMPORAL_CLIENT_CERT: str | None = os.getenv("TEMPORAL_CLIENT_CERT", None)
TEMPORAL_CLIENT_KEY: str | None = os.getenv("TEMPORAL_CLIENT_KEY", None)
TEMPORAL_WORKFLOW_MAX_ATTEMPTS: str = os.getenv("TEMPORAL_WORKFLOW_MAX_ATTEMPTS", "3")
TEMPORAL_USE_PYDANTIC_CONVERTER: bool = get_from_env("TEMPORAL_USE_PYDANTIC_CONVERTER", False, type_cast=str_to_bool)

TEMPORAL_SECRET_KEY: str = os.getenv("TEMPORAL_SECRET_KEY", SECRET_KEY)
TEMPORAL_FALLBACK_SECRET_KEYS: list[str] = get_list(os.getenv("TEMPORAL_FALLBACK_SECRET_KEYS", "")) or [SECRET_KEY]


GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS: int | None = get_from_env(
    "GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS", None, optional=True, type_cast=int
)
MAX_CONCURRENT_WORKFLOW_TASKS: int | None = get_from_env(
    "MAX_CONCURRENT_WORKFLOW_TASKS", None, optional=True, type_cast=int
)
MAX_CONCURRENT_ACTIVITIES: int | None = get_from_env("MAX_CONCURRENT_ACTIVITIES", None, optional=True, type_cast=int)
TARGET_MEMORY_USAGE: float | None = get_from_env("TARGET_MEMORY_USAGE", None, optional=True, type_cast=float)
TARGET_CPU_USAGE: float | None = get_from_env("TARGET_CPU_USAGE", None, optional=True, type_cast=float)

TEMPORAL_HEALTH_PORT: int | None = get_from_env("TEMPORAL_HEALTH_PORT", None, optional=True, type_cast=int)
TEMPORAL_HEALTH_MAX_IDLE_SECONDS: float | None = get_from_env(
    "TEMPORAL_HEALTH_MAX_IDLE_SECONDS", None, optional=True, type_cast=float
)
TEMPORAL_COMBINED_METRICS_SERVER_ENABLED: bool = get_from_env(
    "TEMPORAL_COMBINED_METRICS_SERVER_ENABLED", True, type_cast=str_to_bool
)

# PostHog project where Temporal worker logs are ingested, used to build logs links
# in Temporal UI workflow details. Set to 0 to disable the links.
TEMPORAL_LOGS_PROJECT_ID: int = get_from_env("TEMPORAL_LOGS_PROJECT_ID", 1, type_cast=int)

TEMPORAL_LOG_LEVEL: str = os.getenv("TEMPORAL_LOG_LEVEL", "INFO")
TEMPORAL_OTEL_PLUGIN_ENABLED: bool = get_from_env("TEMPORAL_OTEL_PLUGIN_ENABLED", False, type_cast=str_to_bool)
TEMPORAL_OTEL_LIBRARIES_TO_INSTRUMENT: list[str] = get_list(os.getenv("TEMPORAL_OTEL_LIBRARIES_TO_INSTRUMENT", ""))

SANDBOX_PROVIDER: str | None = get_from_env(
    "SANDBOX_PROVIDER", None, optional=True
)  # When not set: defaults to "docker" in DEBUG mode, "modal" in production
SANDBOX_API_URL: str | None = get_from_env("SANDBOX_API_URL", None, optional=True)
# Hogland (Firecracker microVM sandbox service) control plane. Deliberately not
# SANDBOX_*-prefixed: agentsh folds SANDBOX_* URL settings into the in-box egress
# allowlist, and the box never needs to reach the hogland control plane.
HOGLAND_API_URL: str | None = get_from_env("HOGLAND_API_URL", None, optional=True)
HOGLAND_API_TOKEN: str | None = get_from_env("HOGLAND_API_TOKEN", None, optional=True)
# Projected ServiceAccount token file (rotating JWT). When set and readable it wins
# over the static HOGLAND_API_TOKEN, which stays as a local-dev/bake-only fallback.
HOGLAND_API_TOKEN_FILE: str | None = get_from_env("HOGLAND_API_TOKEN_FILE", None, optional=True)
SANDBOX_LLM_GATEWAY_URL: str | None = get_from_env("SANDBOX_LLM_GATEWAY_URL", None, optional=True)
# The Go ai-gateway runs on its own host (ai-gateway.*, vs the Python gateway.*), so the
# base URL is what selects it: no product slug on the path, attribution as one
# X-PostHog-Properties blob. SANDBOX_AI_GATEWAY_PRODUCTS limits the switch to named
# ai_product values so one product migrates without moving every other sandbox caller.
# Both must be set; clearing either rolls back to the Python gateway.
SANDBOX_AI_GATEWAY_URL: str | None = get_from_env("SANDBOX_AI_GATEWAY_URL", None, optional=True)
SANDBOX_AI_GATEWAY_PRODUCTS: str | None = get_from_env("SANDBOX_AI_GATEWAY_PRODUCTS", None, optional=True)
# Gateway credential (phs_) the worker uses to mint per-run phe_ scoped tokens for
# gateway-routed sandbox runs. Unset: runs get no token and the agent server keeps them
# on the Python gateway, so the routing allowlist above is inert without it.
SANDBOX_AI_GATEWAY_MINT_KEY: str | None = get_from_env("SANDBOX_AI_GATEWAY_MINT_KEY", None, optional=True)
# Per-run spend cap and token lifetime for minted scoped tokens. The cap bounds one
# runaway run; the daily bound per team is cap x the scheduler's runs-per-day limit.
# The cap must fit a run's real spend plus its in-flight admission holds: a cap near
# typical spend ends runs after the work is written and before it is committed.
# TTL 0 (the default) derives TASKS_MAX_RUN_DURATION_SECONDS + 1h so a capped run
# never outlives its token; a positive value overrides.
SANDBOX_AI_GATEWAY_TOKEN_CAP_USD: str = get_from_env("SANDBOX_AI_GATEWAY_TOKEN_CAP_USD", "10")
# Per-team per-run cap overrides as a JSON object of team id to dollars, e.g. {"2": "10"}.
SANDBOX_AI_GATEWAY_TOKEN_CAP_USD_OVERRIDES: str = get_from_env("SANDBOX_AI_GATEWAY_TOKEN_CAP_USD_OVERRIDES", "")
SANDBOX_AI_GATEWAY_TOKEN_TTL_SECONDS: int = get_from_env("SANDBOX_AI_GATEWAY_TOKEN_TTL_SECONDS", 0, type_cast=int)
SANDBOX_MCP_URL: str | None = get_from_env("SANDBOX_MCP_URL", None, optional=True)

# OTLP destinations for agent-server run telemetry (PostHog Logs/APM).
# Full ingest URLs (e.g. https://us.i.posthog.com/i/v1/logs and .../i/v1/traces)
# plus the project API key of the telemetry project. Telemetry stays off unless
# URL + token are set; the traces URL additionally enables APM spans.
SANDBOX_AGENT_OTEL_LOGS_URL: str | None = get_from_env("SANDBOX_AGENT_OTEL_LOGS_URL", None, optional=True)
SANDBOX_AGENT_OTEL_LOGS_TOKEN: str | None = get_from_env("SANDBOX_AGENT_OTEL_LOGS_TOKEN", None, optional=True)
SANDBOX_AGENT_OTEL_TRACES_URL: str | None = get_from_env("SANDBOX_AGENT_OTEL_TRACES_URL", None, optional=True)

# client_id of the OAuthApplication used to mint the access token the PostHog setup wizard
# uses when it runs inside a task sandbox (the "run the wizard in the cloud" onboarding path).
# It must be the wizard's own app so the LLM gateway authorizes the token like a normal wizard
# run and the token carries the wizard's scope ceiling. Empty disables cloud wizard runs.
WIZARD_CLOUD_RUN_OAUTH_CLIENT_ID: str = get_from_env("WIZARD_CLOUD_RUN_OAUTH_CLIENT_ID", "")

# When True, cloud-to-cloud resume can create legacy Modal filesystem snapshots
# at end-of-run. Modal filesystem image storage is not EU-compliant, so this is
# forced off in EU. Directory snapshots are controlled separately by feature flag
# and may still be created when this setting is False.
TASKS_USE_MODAL_RESUME_SNAPSHOTS: bool = get_from_env(
    "TASKS_USE_MODAL_RESUME_SNAPSHOTS",
    CLOUD_DEPLOYMENT != "EU",
    type_cast=str_to_bool,
)

# Force-enables process_task continue_as_new regardless of the tasks-continue-as-new flag
# (for local E2E / emergency on). The flag is the normal cloud toggle. continue_as_new bounds
# replay cost so long runs don't trip the 2s workflow-task deadlock detector on eviction.
TASKS_CONTINUE_AS_NEW_ENABLED: bool = get_from_env(
    "TASKS_CONTINUE_AS_NEW_ENABLED",
    False,
    type_cast=str_to_bool,
)

TASKS_COMPUTE_QUOTA_ENFORCEMENT_ENABLED: bool = get_from_env(
    "TASKS_COMPUTE_QUOTA_ENFORCEMENT_ENABLED",
    False,
    type_cast=str_to_bool,
)

# Event-count threshold for the above; 0 relies on Temporal's is_continue_as_new_suggested().
TASKS_CONTINUE_AS_NEW_HISTORY_THRESHOLD: int = get_from_env(
    "TASKS_CONTINUE_AS_NEW_HISTORY_THRESHOLD", 4000, type_cast=int
)

# Override the process_task workflow's inactivity timeout (default 2 hours).
# Set this to e.g. 30 for local testing of the shutdown / resume flow. When
# set, the CI-follow-up floor is also bypassed so the timer actually fires
# fast.
TASKS_INACTIVITY_TIMEOUT_SECONDS: int = get_from_env("TASKS_INACTIVITY_TIMEOUT_SECONDS", 0, type_cast=int)

# Hard wall-clock cap on a process_task run, measured from the start of the
# continue_as_new chain and never reset by heartbeats, so it bounds total run time even
# while a wedged agent keeps heartbeating. Interactive sessions are exempt at the call
# site. Set low (e.g. 60) for local testing; 0 or negative disables the cap entirely,
# matching TASKS_INACTIVITY_TIMEOUT_SECONDS above.
TASKS_MAX_RUN_DURATION_SECONDS: int = get_from_env("TASKS_MAX_RUN_DURATION_SECONDS", 3 * 60 * 60, type_cast=int)

# Wall-clock cap for *interactive* signals-origin runs (Inbox "Create PR" / "Discuss", scout
# chat), which are exempt from TASKS_MAX_RUN_DURATION_SECONDS above. Their inference is unbilled,
# so without this their only time bound is the heartbeat-reset inactivity timer. Defaults to the
# sandbox TTL: it never ends a conversation the sandbox wouldn't have ended anyway, but it does
# bound snapshot-resume chains and wedged-but-heartbeating agents. 0 or negative disables.
TASKS_INTERACTIVE_SIGNALS_MAX_RUN_DURATION_SECONDS: int = get_from_env(
    "TASKS_INTERACTIVE_SIGNALS_MAX_RUN_DURATION_SECONDS", 6 * 60 * 60, type_cast=int
)

# Override the delay before the first in-sandbox credential refresh (default 20
# minutes). Set this low (e.g. 30) for local testing so the refresh loop fires
# quickly instead of waiting out the GitHub token's lifetime.
TASKS_CREDENTIAL_REFRESH_INITIAL_DELAY_SECONDS: int = get_from_env(
    "TASKS_CREDENTIAL_REFRESH_INITIAL_DELAY_SECONDS", 0, type_cast=int
)

# Mirror persisted task-run logs into the PostHog Logs product (dogfooding).
# Entries appended to a run's S3 JSONL log are also emitted as structured stdout log lines;
# the per-cluster OTel collector already ships container stdout into the region's internal
# PostHog project's Logs, so no transport or credentials are needed here. Only runs whose
# task origin_product is in this list are mirrored. Set it empty to disable.
TASK_RUN_LOGS_MIRROR_ORIGIN_PRODUCTS: list[str] = get_list(
    os.getenv("TASK_RUN_LOGS_MIRROR_ORIGIN_PRODUCTS", "signals_scout,user_created")
)

# Direct OTLP delivery for the mirror above. The token pins the destination: scout runs
# execute for customer teams, but their mirrored logs must only ever land in (and bill)
# PostHog's own internal logs project — so this is the internal project's API key, never
# derived from the run's team. Point locally at the dev logs ingest to see mirrored runs
# in /logs. Unset disables the direct leg (stdout emission for the collector remains).
TASK_RUN_LOGS_MIRROR_OTLP_URL: str | None = get_from_env("TASK_RUN_LOGS_MIRROR_OTLP_URL", None, optional=True)
TASK_RUN_LOGS_MIRROR_OTLP_TOKEN: str | None = get_from_env("TASK_RUN_LOGS_MIRROR_OTLP_TOKEN", None, optional=True)

TEMPORAL_LOG_LEVEL_PRODUCE: str = os.getenv("TEMPORAL_LOG_LEVEL_PRODUCE", "DEBUG")
TEMPORAL_EXTERNAL_LOGS_QUEUE_SIZE: int = get_from_env("TEMPORAL_EXTERNAL_LOGS_QUEUE_SIZE", 0, type_cast=int)

CLICKHOUSE_MAX_EXECUTION_TIME: int = get_from_env("CLICKHOUSE_MAX_EXECUTION_TIME", 86400, type_cast=int)  # 1 day
CLICKHOUSE_MAX_MEMORY_USAGE: int = get_from_env(
    "CLICKHOUSE_MAX_MEMORY_USAGE", 150 * 1000 * 1000 * 1000, type_cast=int
)  # 150GB
CLICKHOUSE_MAX_BLOCK_SIZE_DEFAULT: int = get_from_env("CLICKHOUSE_MAX_BLOCK_SIZE_DEFAULT", 10000, type_cast=int)
# Comma separated list of overrides in the format "team_id:block_size"
CLICKHOUSE_MAX_BLOCK_SIZE_OVERRIDES: dict[int, int] = dict(
    [map(int, o.split(":")) for o in os.getenv("CLICKHOUSE_MAX_BLOCK_SIZE_OVERRIDES", "").split(",") if o]  # type: ignore
)


# Temporal task queues
# Temporal has a limitation where a worker can only listen to a single queue.
# To avoid running multiple workers, when running locally (DEBUG=True), we use a single queue for all tasks.
# In production (DEBUG=False), we use separate queues for each worker type.
def _set_temporal_task_queue(task_queue: str) -> str:
    if DEBUG:
        return "development-task-queue"
    return task_queue


default_task_queue = os.getenv("TEMPORAL_TASK_QUEUE", "general-purpose-task-queue")
TEMPORAL_TASK_QUEUE: str = _set_temporal_task_queue(default_task_queue)
DATA_WAREHOUSE_TASK_QUEUE = _set_temporal_task_queue("data-warehouse-task-queue")
DATA_WAREHOUSE_CDP_PRODUCER_TASK_QUEUE = _set_temporal_task_queue("data-warehouse-cdp-producer-task-queue")
# Post-sync table metadata (semantic enrichment + column statistics) runs on its own worker so this
# best-effort work can't starve the import pipeline.
DATA_WAREHOUSE_METADATA_TASK_QUEUE = _set_temporal_task_queue("data-warehouse-metadata-task-queue")
MAX_AI_TASK_QUEUE = _set_temporal_task_queue("max-ai-task-queue")
BATCH_EXPORTS_TASK_QUEUE = _set_temporal_task_queue("batch-exports-task-queue")
DATA_MODELING_TASK_QUEUE = _set_temporal_task_queue("data-modeling-task-queue")
SYNC_BATCH_EXPORTS_TASK_QUEUE = _set_temporal_task_queue("no-sandbox-python-django")
GENERAL_PURPOSE_TASK_QUEUE = _set_temporal_task_queue("general-purpose-task-queue")
# Defaults to the general-purpose fleet so dispatch always has a live worker; set the env to
# "signup-enrichment-task-queue" to route unauthenticated signup enrichment to a dedicated,
# separately-scalable worker once one is deployed.
SIGNUP_ENRICHMENT_TASK_QUEUE = _set_temporal_task_queue(
    os.getenv("SIGNUP_ENRICHMENT_TASK_QUEUE", "general-purpose-task-queue")
)
# Defaults to the general-purpose fleet so dispatch always has a live worker. Routing canvas
# builds to a dedicated, separately-scalable worker takes two steps in order: deploy a worker
# fleet polling "canvas-build-task-queue" (a charts change), then set this env on the
# dispatching services. Setting it first strands builds on a pollerless queue until the
# workflow execution timeout closes them.
CANVAS_BUILD_TASK_QUEUE = _set_temporal_task_queue(os.getenv("CANVAS_BUILD_TASK_QUEUE", "general-purpose-task-queue"))
EXPERIMENTS_RECALCULATION_TASK_QUEUE = _set_temporal_task_queue("experiments-recalculation-task-queue")
HEALTH_CHECK_TASK_QUEUE = _set_temporal_task_queue("health-check-task-queue")
DUCKLAKE_TASK_QUEUE = _set_temporal_task_queue("ducklake-task-queue")
TASKS_TASK_QUEUE = _set_temporal_task_queue("tasks-task-queue")
TASKS_DISPATCHER_BATCH_SIZE = get_from_env("TASKS_DISPATCHER_BATCH_SIZE", 50, type_cast=int)
TASKS_DISPATCHER_CONCURRENCY = get_from_env("TASKS_DISPATCHER_CONCURRENCY", 20, type_cast=int)
TASKS_DISPATCHER_LEASE_SECONDS = get_from_env("TASKS_DISPATCHER_LEASE_SECONDS", 60, type_cast=int)
TASKS_DISPATCHER_POLL_INTERVAL_SECONDS = get_from_env("TASKS_DISPATCHER_POLL_INTERVAL_SECONDS", 1.0, type_cast=float)
TASKS_DISPATCHER_RPC_TIMEOUT_SECONDS = get_from_env("TASKS_DISPATCHER_RPC_TIMEOUT_SECONDS", 10, type_cast=int)
TASKS_DISPATCHER_MAX_DISPATCH_AGE_SECONDS = get_from_env(
    "TASKS_DISPATCHER_MAX_DISPATCH_AGE_SECONDS", 6 * 60 * 60, type_cast=int
)
STAMPHOG_TASK_QUEUE = _set_temporal_task_queue("stamphog-task-queue")
TEST_TASK_QUEUE = _set_temporal_task_queue("test-task-queue")
BILLING_TASK_QUEUE = _set_temporal_task_queue("billing-task-queue")
VIDEO_EXPORT_TASK_QUEUE = _set_temporal_task_queue("video-export-task-queue")
ANALYTICS_PLATFORM_TASK_QUEUE = _set_temporal_task_queue("analytics-platform-task-queue")
SESSION_REPLAY_TASK_QUEUE = _set_temporal_task_queue("session-replay-task-queue")
REPLAY_VISION_TASK_QUEUE = _set_temporal_task_queue("replay-vision-task-queue")
# The XGBoost-based session surfacing scoring sweep runs on the session-replay
# worker (it's the only OpenMP user there; that worker sets OMP_NUM_THREADS=1).
# Sharing the queue means start_temporal_worker aggregates its workflow +
# activities onto the replay worker and warmup() runs on replay-worker boot —
# no dedicated pod needed (see surfacing_scoring_sweep/README.md).
SURFACING_SCORING_SWEEP_TASK_QUEUE = SESSION_REPLAY_TASK_QUEUE
WEEKLY_DIGEST_TASK_QUEUE = _set_temporal_task_queue("weekly-digest-task-queue")
LLMA_EVALS_TASK_QUEUE = _set_temporal_task_queue("llm-analytics-evals-task-queue")
LLMA_TASK_QUEUE = _set_temporal_task_queue("llm-analytics-task-queue")
# Defaults to the general-purpose fleet so dispatch always has a live worker; set the env to
# "mcp-analytics-task-queue" to route MCP analytics clustering to a dedicated, separately-scalable
# worker once one is deployed.
MCPA_TASK_QUEUE = _set_temporal_task_queue(os.getenv("MCPA_TASK_QUEUE", "general-purpose-task-queue"))
ERROR_TRACKING_TASK_QUEUE = _set_temporal_task_queue("error-tracking-task-queue")
ERROR_TRACKING_LIFECYCLE_TASK_QUEUE = _set_temporal_task_queue("error-tracking-lifecycle-task-queue")
EVENT_SCREENSHOTS_TASK_QUEUE = _set_temporal_task_queue("event-screenshots-task-queue")
LOGS_ALERTING_TASK_QUEUE = _set_temporal_task_queue("logs-alerting-task-queue")
# Dedicated queue: the tick becomes the scan-heavy rollup writer, and it must not
# share pods with the latency-sensitive alerting workers.
LOGS_VOLUME_TICK_TASK_QUEUE = _set_temporal_task_queue(
    os.getenv("LOGS_VOLUME_TICK_TASK_QUEUE", "logs-volume-tick-task-queue")
)
RASTERIZATION_TASK_QUEUE = "rasterization-task-queue"  # Not collapsed in dev — separate Node.js worker process

# Error tracking
# Global on/off switch for auto-merging close fingerprints into their nearest issue.
# Off by default; enabled per-deployment (e.g. EU).
ERROR_TRACKING_AUTO_MERGE_ENABLED: bool = get_from_env(
    "ERROR_TRACKING_AUTO_MERGE_ENABLED", False, type_cast=str_to_bool
)

# Signals inbox notification: how long to wait for an auto-started implementation PR before
# notifying anyway, and how often to poll for it.
SIGNALS_INBOX_PR_NOTIFICATION_TIMEOUT_SECONDS: int = get_from_env(
    "SIGNALS_INBOX_PR_NOTIFICATION_TIMEOUT_SECONDS", 1800, type_cast=int
)
SIGNALS_INBOX_PR_NOTIFICATION_POLL_SECONDS: int = get_from_env(
    "SIGNALS_INBOX_PR_NOTIFICATION_POLL_SECONDS", 30, type_cast=int
)

# Incoming webhook for experiment precompute canary divergence alerts. Unset: Slack alerting is skipped.
EXPERIMENT_CANARY_SLACK_WEBHOOK_URL: str = os.getenv("EXPERIMENT_CANARY_SLACK_WEBHOOK_URL", "")
