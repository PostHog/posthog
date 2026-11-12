# Internal senders

Every place PostHog code sends events to capture, and which capture it uses at the first v1 release.
The legacy entries move to v1 soon after that release. Update this list and the skill when each one moves.

## On capture v1

| Sender                                     | Code                                                                                                                                   | Sends to                                                            |
| ------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| Django, on behalf of a customer team       | `capture_internal`, `capture_batch_internal` in [`posthog/api/capture.py`](../../../../posthog/api/capture.py)                         | `/i/v1/analytics/events` (`CAPTURE_V1_INTERNAL_ENDPOINT`)           |
| Django, `$ai_*` events for a customer team | `capture_ai_internal` in the same file, for example [`team_capture.py`](../../../../posthog/temporal/ai_observability/team_capture.py) | `/i/v1/ai/events` on capture-ai (`CAPTURE_V1_AI_INTERNAL_ENDPOINT`) |
| Node push subscription person updates      | [`push-capture.ts`](../../../../nodejs/src/messaging/push-subscriptions/push-capture.ts)                                               | `/i/v1/analytics/events`                                            |
| Batch imports                              | [`batch-import-worker/src/emit/capture.rs`](../../../../rust/batch-import-worker/src/emit/capture.rs)                                  | `/i/v1/analytics/events`                                            |
| Rust services' own telemetry               | posthog-rs with the `capture-v1` feature (`posthog-rs` in [`rust/Cargo.toml`](../../../../rust/Cargo.toml))                            | `/i/v1/*`                                                           |

To find the Django call sites, search for `capture_internal(`, `capture_batch_internal(` and `capture_ai_internal(`.

## Still on legacy capture at the first v1 release

| Sender                                                                  | Code                                                                                                                                                                                                                                                      | Sends to   |
| ----------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| Node internal capture, used by CDP `posthog.capture()` in Hog functions | `InternalCaptureService` in [`internal-capture.ts`](../../../../nodejs/src/common/services/internal-capture.ts), `CAPTURE_INTERNAL_URL` in [`config.ts`](../../../../nodejs/src/common/config.ts)                                                         | `/capture` |
| Django and `ee/` team 2 telemetry                                       | `posthoganalytics` (posthog-python 7.x) in [`pyproject.toml`](../../../../pyproject.toml), held below 8 by `constraint-dependencies`                                                                                                                      | Legacy     |
| Node services' own telemetry                                            | `posthog-node` 5.x in [`nodejs/package.json`](../../../../nodejs/package.json), [`services/mcp/package.json`](../../../../services/mcp/package.json) and [`products/desktop/apps/code/package.json`](../../../../products/desktop/apps/code/package.json) | Legacy     |
| PostHog CLI                                                             | `posthog-rs` 0.30 without the `capture-v1` feature in [`cli/Cargo.toml`](../../../../cli/Cargo.toml)                                                                                                                                                      | Legacy     |
| Hobby installer                                                         | `posthog-go` v1 in [`bin/hobby-installer/go.mod`](../../../../bin/hobby-installer/go.mod)                                                                                                                                                                 | Legacy     |

The batch import worker can also write to Kafka directly ([`emit/kafka.rs`](../../../../rust/batch-import-worker/src/emit/kafka.rs)). That is the one existing exception to "send through capture".
