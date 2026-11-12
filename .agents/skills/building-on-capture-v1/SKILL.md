---
name: building-on-capture-v1
description: >
  How to build on capture v1, PostHog's batch event intake API (`/i/v1/analytics/events`, `/i/v1/ai/events`).
  Use when sending events to capture from PostHog code, changing `rust/capture/src/v1/`, adding a per-event option
  (`event.options`) or a property that capture or ingestion must read, changing how Node ingestion or livestream
  applies capture `options`, changing the v1 request, batch, header or event schema, or checking whether an SDK or
  internal service uses capture v1 or legacy capture (`/batch`, `/e`, `/capture`, `$process_person_profile` or
  `$cookieless_mode` set as properties). Covers when to add an option versus a property and why options exist, the
  files to change for a new option, how to compose a v1 event at a call site, internal senders, and how to tell a v1
  SDK from a legacy one.
---

# Building on capture v1

Capture v1 is the batch intake API that the v1 SDKs and PostHog's internal senders use.
Legacy capture (`/batch`, `/e`, `/capture`, `/i/v0/e`) still serves older SDKs and stays supported, but new senders use v1.

Sources of truth, in the order to read them:

- [`rust/capture/src/v1/README.md`](../../../rust/capture/src/v1/README.md): the request, response and options contract, and how capture hands events to ingestion.
- The `capture` spec in [PostHog/sdk-specs](https://github.com/PostHog/sdk-specs/blob/main/openspec/specs/capture/spec.md): what every v1 SDK does.
- Public docs: the [capture v1 API](https://posthog.com/docs/api/capture-v1) for HTTP senders, and the [SDK upgrade guide](https://posthog.com/docs/libraries/capture-v1) for SDK users.

## Send events from PostHog code

- **On behalf of a customer team, from Django:** use `capture_internal` or `capture_batch_internal` for analytics events, and `capture_ai_internal` for `$ai_*` events, from [`posthog/api/capture.py`](../../../posthog/api/capture.py).
  They implement the headers, retries and per-event results, so do not write a new HTTP client.
- **From Node:** follow [`push-capture.ts`](../../../nodejs/src/messaging/push-subscriptions/push-capture.ts). **From Rust:** follow [`batch-import-worker/src/emit/capture.rs`](../../../rust/batch-import-worker/src/emit/capture.rs).
- **PostHog's own telemetry (team 2):** use the PostHog SDK for the language, on its v1 major.
- Never produce to the ingestion Kafka topics directly. Capture owns quotas, restrictions, deduplication and routing.
- Some internal senders and internal SDK installs still use legacy capture at the first v1 release. [references/internal-senders.md](references/internal-senders.md) lists every sender and which capture it uses. Those move to v1 soon after the release; update the list and this skill when they do. Do not move one in an unrelated PR.

### Compose a v1 event

- Put settings in `options` explicitly, for example `{"process_person_profile": false}`. Never set them as `$process_person_profile`, `$cookieless_mode`, `$ignore_sent_at` or `$product_tour_id` properties.
  An HTTP sender has no SDK to move those properties into options, and capture ignores `$ignore_sent_at` and `$product_tour_id` in `properties`.
- Send `session_id` and `window_id` as event fields, not as `$session_id` and `$window_id` properties.
- For events sent on a customer's behalf, set `"capture_internal": true` on the batch, not in `properties`. Capture then records `127.0.0.1` instead of the PostHog server's IP. Capture v1 ignores a `capture_internal` property, which is where legacy capture reads it.
- Send `$ai_*` events to `/i/v1/ai/events` and every other event to `/i/v1/analytics/events`.
  Capture still routes `$ai_*` events from the analytics endpoint to the AI topic, but only for now. Do not rely on it.
- Give every event its own UUID. On a retry, resend only the events with result `retry`, with the same uuid, `PostHog-Request-Id` and `created_at`, `PostHog-Attempt` plus one, and a new `PostHog-Request-Timestamp`.
- Set `PostHog-Sdk-Info` to `<sender>/<version>`. Ingestion uses it as `$lib` and `$lib_version` only when the event has no `$lib`.

## Choose an option or a property

**Why options exist.** Legacy capture took settings as `$` properties inside the event data.
Capture forwards `properties` to Kafka as raw JSON, and the client controls them, so capture could not act on a setting and ingestion could not trust one.
Capture v1 moves settings into a separate `options` object.
Capture validates each option, acts on it, and publishes it beside the event in the Kafka message, outside the client-controlled data.
Ingestion then writes the matching `$` property, so products and queries read the same property as before.

**The rule:**

- Add an **option** when capture must read, act on or change the value: timestamps, partitioning, quotas, routing or a drop decision. If services after capture also need the value, ingestion copies the option into a property.
- Add a **property** when only ingestion or later services read or change the value. A new property needs no capture change.

Any v1 sender can put any string key with any JSON value in `options`, as with `properties`.
Every v1 SDK passes unknown option keys through unchanged, so a new option needs no SDK change.
The v1 SDKs move the four legacy `$` properties into options under the option names (see the mapping in the [SDK upgrade guide](https://posthog.com/docs/libraries/capture-v1#event-options-replace-legacy-option-properties) and the [sdk-specs capture spec](https://github.com/PostHog/sdk-specs/blob/main/openspec/specs/capture/spec.md#requirement-per-event-options-replace-the-legacy-option-properties)).
A new option has no legacy property: capture relays it in the Kafka message, and ingestion writes it into `properties` when later services need it.

Options are costly to add.
Capture tracks known keys in an 8-bit set (`OptionKeys` in [`analytics/types.rs`](../../../rust/capture/src/v1/analytics/types.rs)), every consumer of the Kafka `options` keeps its own list of keys, and an option name is public API.
Do not add one without agreement from the ingestion team and the SDK owners.

## Add an option

Change all of these in one PR, or in an ordered stack where consumers ship before capture sends the key:

1. Capture, [`analytics/types.rs`](../../../rust/capture/src/v1/analytics/types.rs): `Options`, `ExpectedOption` (`ALL`, `as_str`), the coercer and branch in `RawOptions::validate`, `OutboundOptions` and `outbound_options`, and `build_property_injections` while the splice code exists. Act on the value where capture needs it (for example `process.rs`, or `has_property` for a quota predicate).
2. Capture tests: the option tests in `analytics/types.rs`, [`test_utils.rs`](../../../rust/capture/src/v1/test_utils.rs) and [`tests/v1_publish.rs`](../../../rust/capture/tests/v1_publish.rs).
3. Consumers of the Kafka `options`: `CAPTURE_OPTION_OVERRIDES` in [`parse-kafka-message.ts`](../../../nodejs/src/ingestion/common/steps/event-preprocessing/parse-kafka-message.ts) and its test, and [`livestream/events/kafka.go`](../../../livestream/events/kafka.go).
   Services that read and re-produce capture messages must keep the `options` field and the `legacy_property_splice` header (`CapturedEvent` and `CapturedEventHeaders` in [`common/types/src/event.rs`](../../../rust/common/types/src/event.rs), used by kafka-deduplicator).
4. Internal senders: `_OPTIONS_TO_LEGACY_PROPERTY` and the docstring table in [`posthog/api/capture.py`](../../../posthog/api/capture.py) (test: `posthog/api/test/test_capture_internal.py`), and `OPTIONS_TO_LEGACY_PROPERTY` in [`push-capture.ts`](../../../nodejs/src/messaging/push-subscriptions/push-capture.ts). Only a key that replaces a legacy property needs an entry.
5. Docs and specs: the `invalid_options` entry in [`resolving-ingestion-warnings`](../../../products/ingestion/skills/resolving-ingestion-warnings/SKILL.md), the options table in the v1 README, the sdk-specs `capture` spec, and the public capture v1 API docs.
   SDKs change only when an SDK sets the option itself or has a typed options class, such as posthog-kmp's `PostHogEventOptions`. SDK behavior changes need the capture v1 suites in the SDK test harness.

## Change capture v1 code

- Keep every per-event failure a per-event result. Only the cases in the README's "Response" section fail the whole request.
- `details` values are public: SDKs and docs name them. Add a new one as a constant in `analytics/constants.rs`.
- SDKs on old versions keep sending for years, so contract changes stay backward compatible: a new header or field is optional, and a new result or `details` value only adds to the old ones.
  Update the README, the sdk-specs `capture` spec and the public capture v1 API docs in the same change.
- Watch the change with [`monitoring-capture-service`](../monitoring-capture-service/SKILL.md).

## Check whether an SDK uses capture v1

An SDK is on v1 when it posts to `/i/v1/analytics/events`, sends the `PostHog-Sdk-Info` and `PostHog-Request-Id` headers, and takes `options` on its capture calls.
A legacy SDK posts to `/batch`, `/e` or `/capture` and sets settings as `$` properties.

The v1 majors are:

- posthog-python 8, posthog-go v2, posthog-rs 1.0 and posthog-node 6 (with `@posthog/ai` 8 and `@posthog/mcp` 1 on it).
- posthog-ios 4.0, posthog-android 4.0, and posthog_flutter 6.0 on every platform except web.
- `@posthog/react-native-plugin` 3.0 for the events it sends natively: crash reports, fatal `$exception` events and push-opened events.
- posthog-kmp 0.11 on Android, iOS, macOS and the JVM.

posthog-js in the browser, React Native JS events, and Flutter and KMP on the web stay on legacy capture.
[references/sdk-implementations.md](references/sdk-implementations.md) shows where each v1 SDK builds its events, the order it applies properties and options in, and how `$lib` is set.

## Related

- [`resolving-ingestion-warnings`](../../../products/ingestion/skills/resolving-ingestion-warnings/SKILL.md): read when a v1 drop or ingestion warning needs explaining to a customer.
- [`adding-ingestion-warnings`](../adding-ingestion-warnings/SKILL.md): read before adding a warning in ingestion for a new option.
- [Person processing handbook](../../../docs/published/handbook/engineering/person-processing.md): read when a change touches `process_person_profile`.
