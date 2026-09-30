# TypeSafe egress

TypeSafe serves Jev, a System One model that answers typed questions (`noul`, `choice`, `score`) about a `state`.
It returns probabilities, not free text.

The request and answer types live in `posthog/llm/system_one.py`, because the Go ai-gateway serves the same API with models PostHog hosts.
A caller builds its client with `build_system_one_client` from `posthog/llm/system_one_client.py`.
It reaches the ai-gateway where `AI_GATEWAY_URL` is set.
PostHog Cloud uses the ai-gateway with a PostHog-hosted System One model. This domain is available only in local development or self-hosted instances, when the caller passes a `TypeSafeFallback`.
The transport rejects TypeSafe requests from Cloud before an HTTP call, even if someone configures an API key or calls it directly.

## Usage policy

TypeSafe is approved for local experiments only. Do not use it for Cloud features.
Use `build_system_one_client(model=..., ai_product=...)` with the PostHog-hosted model on the ai-gateway instead. Do not pass `TypeSafeFallback` for a Cloud feature.
Every caller meets these rules before it merges, and a reviewer blocks a caller that does not:

- **Gate the caller behind a feature flag.** Until launch, the flag reaches PostHog staff only.
- **Send no customer data during the experiment.** Customer data is anything from a customer's project or account: events, persons, recordings, insights, names, and text a user types into PostHog. Use synthetic data or data that PostHog owns.

An API key, feature flag, or customer opt-in cannot enable TypeSafe on PostHog Cloud. Changing the Cloud guard needs a separate privacy review and explicit approval before any customer data can be sent.

An instance without `TYPESAFE_API_KEY` sends nothing.

## Identity

An instance holds a single TypeSafe API key.
The whole instance draws from one budget under the key `typesafe:account:default`.
TypeSafe does not say whether it meters its limits per API key or per account, so treat that as unverified.
With one key per instance, both readings give the same single budget.

## Budget

TypeSafe publishes 1,200 requests per minute and 250,000 tokens per second for Jev 1.13.
It also warns that these limits can change without notice.
The budget reads from settings at acquire time:

- `TYPESAFE_EGRESS_PER_MINUTE_BUDGET` (default 600) stays at half of the published request limit, so a limit that TypeSafe lowers still leaves headroom.
- `TYPESAFE_EGRESS_HOURLY_BUDGET` (default 20,000) is an operator ceiling on spend, because TypeSafe bills every input token.

At the 64k-token request limit and the published input price, the hourly ceiling caps spend at roughly $50 an hour.
Typical requests are far smaller.
The token-per-second limit has no budget of its own.
At typical request sizes of a few hundred tokens, the request budget keeps the token rate far under it.
At the 64k-token maximum, 600 requests a minute would exceed it, and TypeSafe answers with a 429.
A caller that sends large states lowers its own request rate.
Raise both settings when real traffic outgrows them.

## Lanes and callers

The default reserve ladder applies, and `typesafe_request` defaults to `NORMAL`.
`typesafe_request` rejects `CRITICAL`, because a `CRITICAL` call is never shed and would skip the hourly spend ceiling.
Give every caller an explicit lane: `NORMAL` when a person waits for the answer, `BATCH` for background work.
No TypeSafe caller exists on master yet. Each new local caller adds itself here with its lane and its feature flag.

## Rate-limit headers

TypeSafe documents no rate-limit status headers, so the domain declares no gauges.
A 429 can carry `retry-after`, and a 529 means TypeSafe is overloaded.
TypeSafe asks for exponential backoff on both, and the caller owns the retry.
`TypeSafeRequestFailed.status_code` lets a caller defer a 429 or a 529 and drop the rest.
The counter is `typesafe_api_requests_total`, labeled `account, method, endpoint, status_code, source`.

## Auth

`TYPESAFE_API_KEY` authenticates every call as a bearer token.
An instance without one makes no request at all: `system_one` raises `TypeSafeNotConfigured`.

## Typed client

Callers use `client.py` rather than `typesafe_request`.
`system_one(state=..., questions=..., source=..., model=...)` sends one state with a map of `NoulQuestion` and `ChoiceQuestion` entries.
It returns a `SystemOneResult` with one `NoulAnswer` or `ChoiceAnswer` per question id, the versioned model that answered, and the input token count.
It raises `TypeSafeRequestFailed` on an HTTP error, and on a body that lacks the answering model or a complete answer for any question.
A choice outside the options the caller sent, or a choice without a probability for every option, counts as incomplete.
`model` defaults to the `jev-latest` alias. A caller that tunes thresholds against one version pins that version's id, such as `jev-1.13.0`.
Only `POST /v1/systemone` is wired up, and score questions are not.

## Sources

- [Models](https://docs.typesafe.ai/models): Jev 1.13 rate limits (1,200 requests per minute, 250,000 tokens per second), the warning that limits change without notice, billing per input token ($0.042 per million), the 64k context length, the `jev-latest` alias and version pinning, and `retry-after` on a rate-limited response.
- [API reference](https://docs.typesafe.ai/api): the `POST /v1/systemone` request and answer shapes, bearer auth, the `401`, `422`, `429` and `529` statuses, exponential backoff on `429` and `529`, and no documented rate-limit status headers.
- [Choice](https://docs.typesafe.ai/primitives/choice): at most 255 options per choice question.
