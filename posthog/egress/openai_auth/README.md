# OpenAI auth egress

Calls to the OpenAI auth server that refreshes and revokes ChatGPT OAuth tokens for the Codex CLI client.

## Identity

The constant scope `codex-client`.
Every request uses the one public Codex CLI OAuth client id, so there is no per-account identity to budget.
A per-user scope would put one label value per connected ChatGPT account on the counter.

## Budget

None: calls are recorded, never gated (`RecordedEgressClient`).
OpenAI documents no request limit for the OAuth token endpoint.
Add a gate only if OpenAI publishes a request limit for it.

## Lanes and callers

No lanes, because nothing is gated.
`posthog/models/integration/codex.py` is the caller.
It refreshes once when a user connects, once per cloud task run start when the access token is near expiry, and once more on demand when the Codex app-server reports a 401.
It revokes the refresh token when the user disconnects.

## Rate-limit headers

None documented, so the domain declares no gauges.
The counter is `openai_auth_api_requests_total`, labeled `scope, method, endpoint, status_code, source`.

## Auth

The refresh token of the connected ChatGPT account, sent in the request body with the public Codex client id.
No PostHog-owned credential.

## Sources

- The vendored Codex CLI binary (`@openai/codex`, `login/src/auth/manager.rs`): the token endpoint is `https://auth.openai.com/oauth/token`, the revoke endpoint is `https://auth.openai.com/oauth/revoke`, and the client id is `app_EMoamEEZ73f0CkXaXp7hrann`. The binary's refresh error messages name three permanent failures: an expired, an already used, and a revoked refresh token.
- [openai/codex login crate](https://github.com/openai/codex/tree/main/codex-rs/login): the refresh request is a JSON body with `client_id`, `grant_type=refresh_token`, `refresh_token` and `scope=openid profile email`; the response carries `id_token`, `access_token` and `refresh_token`. Unverified: the docs publish no request limit and no rate-limit header for this endpoint.
