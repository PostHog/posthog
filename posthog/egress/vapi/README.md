# Vapi egress

## Identity

A 16-character SHA-256 fingerprint of the API token, so the token never reaches a metric label.

## Budget

None: Vapi calls are recorded, never gated (`RecordedEgressClient`).
Vapi's docs state no REST request limit.
The limit they describe is [concurrent call slots](https://docs.vapi.ai/calls/call-concurrency), which a request-rate budget cannot model.
Add a gate only if Vapi publishes a request limit or starts billing per API call.

## Lanes and callers

No lanes, because nothing is gated.
The user interviews web call creation (`products/user_interviews/backend/presentation/webhooks.py`) is the caller.
It maps Vapi's own 429 to a retryable `VapiWebCallError`.

## Rate-limit headers

Vapi returns none, so the domain declares no gauges.
The counter is `vapi_api_requests_total`, labeled `scope, method, endpoint, status_code, source`.

## Auth

`VAPI_PUBLIC_KEY`, sent as a bearer token.

## Sources

- [Call concurrency](https://docs.vapi.ai/calls/call-concurrency): concurrent call slots. Vapi's docs state no REST request limit.
