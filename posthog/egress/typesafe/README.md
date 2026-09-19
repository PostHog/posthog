# TypeSafe egress

TypeSafe serves Jev, a classifier that answers typed questions (`choice`, `noul`, `score`) about a state document.
It picks from options the caller supplies and returns calibrated probabilities.
It does not write free text.

## Identity

TypeSafe meters per API key, and an instance holds a single key.
The whole instance draws from one budget under the key `typesafe:account:default`.

## Budget

TypeSafe publishes 1,200 requests per minute and 250,000 input tokens per second for a key, and notes that the limits adjust with demand.
The budget stays under the request limit and is read from settings at acquire time:

- `TYPESAFE_EGRESS_PER_MINUTE_BUDGET` (default 600) sits at half the published per-minute limit so our reactive backoff absorbs drift.
- `TYPESAFE_EGRESS_HOURLY_BUDGET` (default 10,000) is an operator ceiling on spend.

TypeSafe bills input tokens only, at $0.042 per million, so a call with a few kilobytes of state costs a fraction of a cent.

## Lanes and callers

The default reserve ladder applies, and `typesafe_request` defaults to `NORMAL`.
Product analytics metadata suggestions (`products/product_analytics/backend/presentation/typesafe_metadata.py`) run on `NORMAL`, because a person waits for the answer.
Nothing in this domain runs `CRITICAL`, because the state Jev classifies is user-supplied text and every caller can leave the field for the person to fill in.

## Rate-limit headers

TypeSafe documents no rate-limit status headers, so the domain declares no gauges.
A 429 or a 529 asks the caller to back off, and the caller owns the retry.
The counter is `typesafe_api_requests_total`, labeled `account, method, endpoint, status_code, source`.

## Auth

`TYPESAFE_API_KEY` authenticates every call as a bearer token.
An instance without one makes no request at all: `system_one` raises `TypesafeNotConfigured`.

## Typed client

Callers use `client.py` rather than `typesafe_request`.
`system_one(state=..., questions=..., source=...)` sends one `POST /v1/systemone` request with the pinned `jev-1.13.0` model and returns a `SystemOneResult` with one `ChoiceAnswer` or `NoulAnswer` per question key.
It raises `TypesafeCallFailed` when TypeSafe answers with anything but a usable result, including an option outside the criteria the caller sent.
A `ChoiceQuestion` rejects an empty option map or more than 255 options before any call.

## Sources

- [Models](https://docs.typesafe.ai/models.md): `jev-1.13.0`, the 1,200 requests per minute and 250,000 tokens per second limits, the 64k context and 32k state limits, and the input-only price.
- [API reference](https://docs.typesafe.ai/api.md): the `POST /v1/systemone` request and response shape, and the 429 and 529 backoff guidance.
- [Choice](https://docs.typesafe.ai/primitives/choice.md): the 255 option cap and the `choice`, `probabilities`, and `confidence` answer fields.
