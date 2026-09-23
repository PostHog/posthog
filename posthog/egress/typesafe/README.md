# TypeSafe egress

## Identity

One TypeSafe account credential serves the instance, so all workers share the `typesafe:account:default` budget.
Credentials and request content never become metric labels.

## Budget

TypeSafe publishes a limit of 1,200 requests per minute and 250,000 tokens per second, subject to change.
The demo uses lower operator ceilings: `TYPESAFE_EGRESS_PER_MINUTE_BUDGET` (600) and `TYPESAFE_EGRESS_HOURLY_BUDGET` (36,000).
Autocomplete can send two batches every 250 milliseconds, so the minute budget allows sustained typing by one user.
These cap requests, not tokens or dollars; the decisions API separately bounds request size.

## Lanes and callers

ML inference sends explicit Jev requests on `NORMAL`, including app search.
The default priority reserves apply.
The `NORMAL` lane can use 90% of each ceiling: 540 requests per minute and 32,400 per hour across the instance.
A denied request or provider error returns through the decisions API; app search falls back to text matching without retrying automatically.

## Rate-limit headers

The model documentation mentions optional `Retry-After`, but does not define quota-status headers.
No gauges are declared.
The request counter uses account, method, endpoint, status code, and source labels.

## Auth

Set `TYPESAFE_API_KEY` on the server.
The transport sends it only to `https://api.typesafe.ai/v1/systemone`, with redirects disabled.
The app-search demo pins `jev-1.13.0`; the existing PostHog decision model remains the default for other callers.

## Sources

- [TypeSafe API](https://docs.typesafe.ai/api): endpoint, bearer authentication, and response format.
- [Models](https://docs.typesafe.ai/models): model identifiers, rate limits, token billing, and optional retry header.
