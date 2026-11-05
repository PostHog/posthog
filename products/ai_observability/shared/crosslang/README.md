# AI event limits

`ai_event_limits.json` holds the size limits and thresholds for AI events (`$ai_*`).
It is the source of truth for these values: the Rust and Node copies follow it, and their parity tests fail when a copy differs.
Every value is in decimal bytes: 100 KB is `100000` and 48 MB is `48000000`.
`max_event_bytes_default` is the exception. It stays at the binary 8 MiB (`8388608`) that deployments run today, until the infrastructure around capture accepts larger events.

| Key                            | Meaning                                                                                                                         |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------- |
| `max_event_bytes_default`      | The largest AI event a project can send unless it has an override.                                                              |
| `max_event_bytes_overrides`    | The larger caps a project can get on request, in ascending order.                                                               |
| `max_event_bytes_ceiling`      | The largest AI event any project can send. SDKs check against this value only, because the per-project cap is the server's job. |
| `included_bytes_per_event`     | The bytes of each event that the event price covers. Size pricing bills the bytes above it.                                     |
| `media_offload_min_bytes`      | The decoded size from which ingestion moves inline media to object storage.                                                     |
| `text_offload_enabled`         | Whether ingestion moves the text content of large events to object storage. Off.                                                |
| `text_offload_min_event_bytes` | The event size from which text offload applies, once it is on.                                                                  |

Values that follow from these are computed by the code that needs them, never stored here.

## Who reads it

- Python reads this file at runtime. Core Django gets the values through `products.ai_observability.backend.facade.limits`.
- Rust capture mirrors the keys it needs in `rust/capture/src/ai_event_limits.rs`.
- The Node AI pipeline mirrors the keys it needs in `nodejs/src/ingestion/common/ai-event-limits.ts`.

The Rust image build context is `rust/` and the Node build compiles from `nodejs/`, so neither can read this file at runtime.
A key `k` is the constant `AI_<K>` in each mirror, for example `max_event_bytes_ceiling` is `AI_MAX_EVENT_BYTES_CEILING`.

## Overrides

- `included_bytes_per_event` takes no environment override, because the Node usage records and the Django usage report must agree on it.
- Capture reads `AI_MAX_EVENT_BYTES` to set a smaller cap for a deployment that needs one. Its default is `max_event_bytes_default`.
- Capture's `AI_MAX_SUM_OF_PARTS_BYTES` bounds a whole multipart request, not an event, and is not one of these values.
- The Node pipeline reads `AI_BLOB_OFFLOAD_MIN_BASE64_LENGTH` as a tuning knob. Its default is the base64 length of `media_offload_min_bytes`.

## How to change a value

1. Edit this file first.
2. Update each mirror that carries the key. Its parity test fails until you do:
   `cargo test -p capture --test ai_event_limits_parity` and `hogli test nodejs/src/ingestion/common/ai-event-limits.test.ts`.
   For `max_event_bytes_default`, also update the `envconfig` default of `ai_max_event_bytes` in `rust/capture/src/config.rs`, which cannot name a constant.
3. A cap change also needs the deployment limits around it, such as the Kafka producer limit and the edge proxy body limit.
