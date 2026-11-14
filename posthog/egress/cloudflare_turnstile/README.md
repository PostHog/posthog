# Cloudflare Turnstile egress

Calls to the Cloudflare Turnstile siteverify API, which checks a token that the Turnstile widget gave a browser.

## Identity

The constant scope `public`.
The instance has one Turnstile secret key, so there is no per-account identity to budget.

## Budget

None: calls are recorded, never gated (`RecordedEgressClient`).
Cloudflare documents no request limit for siteverify.
Add a gate only if Cloudflare publishes a request limit for it.

## Lanes and callers

No lanes, because nothing is gated.
`posthog/turnstile.py` (`verify_login_turnstile_token`) is the caller.
It checks the token that a password login from a new browser sends, once per login request, with a 2-second timeout.
The signup check (`verify_turnstile_token`) still calls siteverify directly and is not yet in this domain.

## Rate-limit headers

None documented, so the domain declares no gauges.
The counter is `cloudflare_turnstile_api_requests_total`, labeled `scope, method, endpoint, status_code, source`.

## Auth

The Turnstile secret key (`CLOUDFLARE_TURNSTILE_SECRET_KEY`), sent in the form body with the token and the visitor IP.
The secret and the token never become metric labels.

## Sources

- [Cloudflare: Validate the token (server-side validation)](https://developers.cloudflare.com/turnstile/get-started/server-side-validation/): the endpoint is `POST https://challenges.cloudflare.com/turnstile/v0/siteverify`; the form fields are `secret`, `response`, and optional `remoteip` and `idempotency_key`; the response carries `success`, `challenge_ts`, `hostname`, `error-codes`, `action` and `cdata`; a token is at most 2048 characters, is valid for 300 seconds, and is meant for single use; the error code `internal-error` asks the caller to retry. The page documents no request limit and no rate-limit header for siteverify.
- [Cloudflare: Testing](https://developers.cloudflare.com/turnstile/troubleshooting/testing/): the test secret keys `1x0000000000000000000000000000000AA` (always passes), `2x0000000000000000000000000000000AA` (always fails) and `3x0000000000000000000000000000000AA` (token already spent); with a test secret, a passing response has hostname `example.com` and no `action` or `cdata`.
