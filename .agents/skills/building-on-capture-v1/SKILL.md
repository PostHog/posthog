---
name: building-on-capture-v1
description: >
  How to build on capture v1, PostHog's batch event intake API (`/i/v1/analytics/events`, `/i/v1/ai/events`).
  Use when sending events to capture from PostHog code, changing `rust/capture/src/v1/`, adding a per-event option
  (`event.options`) or a property that capture or ingestion must read, changing how Node ingestion or livestream
  applies capture `options`, or checking whether an SDK or internal service uses capture v1 or legacy capture
  (`/batch`, `/e`, `/capture`, `$process_person_profile` or `$cookieless_mode` set as properties).
  Covers the option-versus-property decision, the files to change for a new option, internal capture clients, and
  how to tell a v1 SDK from a legacy one.
---

# Building on capture v1

Capture v1 is the event intake API every new sender must use.
Read [`rust/capture/src/v1/README.md`](../../../rust/capture/src/v1/README.md) first for the request, response and options contract.
The cross-SDK contract is the `capture` spec in [PostHog/sdk-specs](https://github.com/PostHog/sdk-specs/blob/main/openspec/specs/capture/spec.md).

## Send events from PostHog code

- **On behalf of a customer team:** use `capture_internal`, `capture_batch_internal` or `capture_ai_internal` from [`posthog/api/capture.py`](../../../posthog/api/capture.py).
  They post to capture v1 and turn legacy option properties into options.
  Never produce to the ingestion Kafka topics directly: capture owns quotas, restrictions, deduplication and routing.
- **PostHog's own telemetry (team 2):** use the PostHog SDK.
  The internal pins are still on pre-v1 majors (`posthoganalytics<8` in `pyproject.toml`, `posthog-node` 5).
  Do not lift a pin in an unrelated PR: moving to the v1 major is its own migration.
- **Node services:** `InternalCaptureService` ([`internal-capture.ts`](../../../nodejs/src/common/services/internal-capture.ts)) still posts to legacy `/capture`.
  [`push-capture.ts`](../../../nodejs/src/messaging/push-subscriptions/push-capture.ts) is the v1 example to follow for a new Node sender.
- Set per-event settings as `options`, never as `$process_person_profile`, `$cookieless_mode`, `$ignore_sent_at` or `$product_tour_id` properties.

## Choose an option or a property

Use an **option** only when one of these is true:

- Capture must act on the value before Kafka: timestamp handling, partitioning, quotas, routing or a drop decision.
  Capture never parses `properties`, so it cannot act on a property.
- Ingestion must trust the value. Capture writes options to the outer Kafka message; `data` is client-controlled.

Use a **property** in every other case, for example a value only an ingestion step, a product or a query reads.
A new property needs no capture change.

Options are scarce.
Capture tracks known keys in an 8-bit set (`OptionKeys` in [`analytics/types.rs`](../../../rust/capture/src/v1/analytics/types.rs)), every SDK must learn a new key, and a rename breaks consumers.
Do not add an option without agreement from the ingestion team and the SDK owners (the option is public API).

## Add an option

Change all of these in one PR, or in an ordered stack where consumers ship before capture sends the key:

1. Capture, [`analytics/types.rs`](../../../rust/capture/src/v1/analytics/types.rs): `Options`, `ExpectedOption` (`ALL`, `as_str`), the coercer and branch in `RawOptions::validate`, `OutboundOptions` and `outbound_options`, and `build_property_injections` while the splice code exists. Act on the value where capture needs it (for example `process.rs`, or `has_property` for a quota predicate).
2. Capture tests: the option tests in `analytics/types.rs`, [`test_utils.rs`](../../../rust/capture/src/v1/test_utils.rs) and [`tests/v1_publish.rs`](../../../rust/capture/tests/v1_publish.rs).
3. Consumers of the outer `options`: `CAPTURE_OPTION_OVERRIDES` in [`parse-kafka-message.ts`](../../../nodejs/src/ingestion/common/steps/event-preprocessing/parse-kafka-message.ts) and its test, and [`livestream/events/kafka.go`](../../../livestream/events/kafka.go).
4. Internal clients: `_OPTIONS_TO_LEGACY_PROPERTY` and the docstring table in [`posthog/api/capture.py`](../../../posthog/api/capture.py) (test: `posthog/api/test/test_capture_internal.py`), and `OPTIONS_TO_LEGACY_PROPERTY` in [`push-capture.ts`](../../../nodejs/src/messaging/push-subscriptions/push-capture.ts).
5. The `invalid_options` entry in [`resolving-ingestion-warnings`](../../../products/ingestion/skills/resolving-ingestion-warnings/SKILL.md), the options table in the v1 README, the sdk-specs `capture` spec, and the public capture v1 API docs.

## Change capture v1 code

- Keep every per-event failure a per-event result. Only the cases in the README's "Response" section fail the whole request.
- A new per-event reason is a new `details` constant in `analytics/constants.rs`, and SDKs and docs may name it, so treat it as public.
- Watch the change with [`monitoring-capture-service`](../monitoring-capture-service/SKILL.md).

## Check whether an SDK uses capture v1

An SDK is on v1 when it posts to `/i/v1/analytics/events`, sends the `PostHog-Sdk-Info` and `PostHog-Request-Id` headers, and takes `options` on its capture calls.
A legacy SDK posts to `/batch`, `/e` or `/capture` and sets settings as `$` properties.

The first v1 majors are posthog-python 8, posthog-go v2, posthog-rs 1.0, posthog-node 6, posthog-ios 4.0, posthog-android 4.0 and posthog_flutter 6.0 (not on web).
posthog-js in the browser and React Native JS stay on legacy capture.
The [SDK upgrade guide](https://posthog.com/docs/libraries/capture-v1) lists versions and migration guides.

## Related

- [`resolving-ingestion-warnings`](../../../products/ingestion/skills/resolving-ingestion-warnings/SKILL.md): read when a v1 drop or ingestion warning needs explaining to a customer.
- [`adding-ingestion-warnings`](../adding-ingestion-warnings/SKILL.md): read before adding a warning in ingestion for a new option.
- [Person processing handbook](../../../docs/published/handbook/engineering/person-processing.md): read when a change touches `process_person_profile`.
