# TypeSafe egress

## Identity

PostHog supplies one API credential to this client.
The operator budget groups calls by the credential's fingerprint, under `typesafe:credential:<fingerprint>`.
The credential itself never becomes a metric label.
The vendor's account-level budget identity is unverified.

## Budget

These are initial operator ceilings for company classification, not vendor request limits:

- `TYPESAFE_EGRESS_PER_MINUTE_BUDGET` defaults to 60 requests, permitting one request per second across callers.
- `TYPESAFE_EGRESS_HOURLY_BUDGET` defaults to 1,000 requests, limiting sustained background classification.

Each request contains both classification questions.
The limits are read from settings when a call requests admission.

## Lanes and callers

The default priority reserve applies.
The growth Jev labeler uses `BATCH`; an interactive caller can explicitly request `NORMAL`.
The transport defaults to `NORMAL` and raises `TypeSafeEgressBudgetExhausted` when admission fails.

## Rate-limit headers

Rate-limit header formats are unverified, so this domain declares no gauges.
The API documents HTTP 429 and 529 as retryable responses.
Callers defer those responses rather than immediately retrying.
`typesafe_api_requests_total` records `credential, method, endpoint, status_code, source`.

## Auth

The caller supplies a bearer token for `POST https://api.typesafe.ai/v1/systemone`.
Requests have finite connect/read timeouts and do not follow redirects.

## Sources

- [API reference](https://docs.typesafe.ai/api): request schema, response schema, authentication, and retryable errors.
- [Quick start](https://docs.typesafe.ai/introduction/quickstart): endpoint and bearer-token authentication.
