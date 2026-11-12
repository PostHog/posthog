# v1 SDK implementations

Read this when a capture or ingestion change depends on what the SDKs send.
The [sdk-specs `capture` spec](https://github.com/PostHog/sdk-specs/blob/main/openspec/specs/capture/spec.md) is the contract. The code below implements it.

## Where each SDK builds its v1 events

| SDK                                      | Builds the event                                                                                                                                             | Sends the batch                                                                                                                                             |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| posthog-python 8                         | [`posthog/capture_event.py`](https://github.com/PostHog/posthog-python/blob/main/posthog/capture_event.py)                                                   | [`posthog/capture_send.py`](https://github.com/PostHog/posthog-python/blob/main/posthog/capture_send.py)                                                    |
| posthog-go v2                            | [`capture_event.go`](https://github.com/PostHog/posthog-go/blob/main/capture_event.go)                                                                       | [`capture_send.go`](https://github.com/PostHog/posthog-go/blob/main/capture_send.go)                                                                        |
| posthog-rs 1.0                           | [`src/capture_event.rs`](https://github.com/PostHog/posthog-rs/blob/main/src/capture_event.rs)                                                               | [`src/client/capture.rs`](https://github.com/PostHog/posthog-rs/blob/main/src/client/capture.rs)                                                            |
| posthog-node 6                           | [`packages/core/src/event-options.ts`](https://github.com/PostHog/posthog-js/blob/main/packages/core/src/event-options.ts)                                   | [`packages/node/src/capture-v1/`](https://github.com/PostHog/posthog-js/tree/main/packages/node/src/capture-v1)                                             |
| posthog-ios 4.0                          | `captureV1JSON` in [`PostHog/PostHogApi.swift`](https://github.com/PostHog/posthog-ios/blob/main/PostHog/PostHogApi.swift)                                   | Same file                                                                                                                                                   |
| posthog-android 4.0                      | `captureV1Json` in [`internal/PostHogApi.kt`](https://github.com/PostHog/posthog-android/blob/main/posthog/src/main/java/com/posthog/internal/PostHogApi.kt) | Same file                                                                                                                                                   |
| posthog_flutter 6.0 on Windows and Linux | [`lib/src/core/capture_v1.dart`](https://github.com/PostHog/posthog-flutter/blob/main/posthog_flutter/lib/src/core/capture_v1.dart)                          | [`lib/src/core/posthog_core_stateless.dart`](https://github.com/PostHog/posthog-flutter/blob/main/posthog_flutter/lib/src/core/posthog_core_stateless.dart) |

posthog_flutter on iOS, macOS and Android, `@posthog/react-native-plugin` 3.0 and posthog-kmp 0.11 send through the native posthog-ios and posthog-android SDKs (posthog-kmp on the JVM uses posthog-android's core module).

## The order of properties and options

Server SDKs (Python, Go, Rust, Node) fill each event from these layers, and a later layer wins:

1. Values the SDK sets.
2. Global properties and options (`super_properties` and `super_options` in Python, `DefaultEventProperties` and `DefaultEventOptions` in Go, `register()` and `registerOptions()` in Node). Rust has no global layer.
3. Context properties and options.
4. The call's own properties and options.

Client SDKs (iOS, Android, Flutter) use the same idea: values the SDK sets, then registered properties, then the event's own properties.

Then, in every v1 SDK:

- `before_send` runs last. What it returns is sent.
- After `before_send`, the SDK removes each legacy `$` option property from `properties` and copies its value into the matching option only when that option is missing or null. An option set at any layer wins over a legacy property set at any layer.

The spec's requirements "Server SDKs build every event in one layer order", "Caller-supplied event properties take precedence" and "Per-event options replace the legacy option properties" give the details.

## `$lib` and `$lib_version`

- Each SDK sets the pair from its own identity after every other layer and before `before_send`. When `$lib` is set to another library, the SDK keeps it and adds no version.
- MCP integrations label their events: posthog-python 8 (`posthog-python-mcp`) on MCP events and their `$exception` events, posthog-go v2 (`posthog-go-mcp`) and posthog-rs 1.0 (`posthog-rs-mcp`) on MCP events. `@posthog/mcp` labels every event of its posthog-node client `posthog-node-mcp`.
- Capture relays the `PostHog-Sdk-Info` header to Kafka as `req_lib` and `req_lib_version`. Ingestion uses them only when the event has no `$lib` (see the v1 README).
- The usage report and SDK Health read `$lib`, so a change here changes what they count.
