# TypeSafe egress

## Identity

TypeSafe meters the account behind an API key. The limiter and metrics use a short SHA-256 fingerprint of the key, never the credential itself.

## Budget

TypeSafe publishes 1,200 requests per minute for Jev. PostHog defaults to 1,000 requests per minute and 50,000 per hour so background verification cannot consume the provider limit or create unbounded spend.

## Lanes and callers

Signals verification uses the `BATCH` lane. A denied call remains an errored, retryable check and does not become a verdict.

## Rate-limit headers

The API documents `Retry-After` for HTTP 429 and 529 responses. The check runner does not sleep inside the coordinator tick; it records a retryable error and uses the check schedule for backoff.

## Auth

Callers pass `TYPESAFE_API_KEY` as a bearer token. The transport is credential-agnostic and never stores it.

## Sources

- [TypeSafe API](https://docs.typesafe.ai/api)
- [Jev models and limits](https://docs.typesafe.ai/models)
