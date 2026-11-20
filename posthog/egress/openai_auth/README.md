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
`posthog/tasks/codex_login.py` requests device codes, polls for approval, and exchanges the authorization code. Polls respect the provider interval. Temporary poll failures back off and honor `Retry-After` within the attempt deadline. The authorization code exchange is not retried, including HTTP rejections. Codex uses this policy for the single-use code. A timeout or rejected exchange ends the attempt; the user starts a new login. Access is checked again before the token transaction commits. A temporary final access failure is retried once after the five-second billing error cache expires. Tokens stay in worker memory and the uncommitted transaction. If access still cannot be verified, the transaction rolls back.

Cache failures before token exchange retry the task up to three times, after the 60-second polling reservation expires. These retries keep the original login deadline. No task retry occurs after token exchange starts. The final access retry holds the user lock for five extra seconds, so cancellation and token issuance for that user wait. This keeps the refreshed tokens and access check in one transaction; cancellation can then remove only the credentials from that attempt.

After token exchange, cancellation-state reads and status publication each have three attempts, two seconds apart. Tokens stay in worker memory while the read retries. Status publication runs after the token transaction commits. Neither retry repeats token exchange, and a publication failure does not mark the committed connection as failed.

The login cache uses a separate connection pool with one-second connect and read timeouts. The final cancellation-state read stays under the user lock to serialize it with cancellation. Its two retry waits can add four seconds to the lock hold time.

Canceling an attempt that stored credentials emits the existing `codex subscription disconnected` user event after the cancellation transaction commits. Repeated cancellation does not emit it again.

## Rate-limit headers

None documented, so the domain declares no gauges.
The counter is `openai_auth_api_requests_total`, labeled `scope, method, endpoint, status_code, source`.

## Auth

The refresh token of the connected ChatGPT account, sent in the request body with the public Codex client id.
No PostHog-owned credential.

## Sources

- The vendored Codex CLI binary (`@openai/codex`, `login/src/auth/manager.rs`): the token endpoint is `https://auth.openai.com/oauth/token`, the revoke endpoint is `https://auth.openai.com/oauth/revoke`, and the client id is `app_EMoamEEZ73f0CkXaXp7hrann`. The binary's refresh error messages name three permanent failures: an expired, an already used, and a revoked refresh token.
- [openai/codex login crate](https://github.com/openai/codex/tree/main/codex-rs/login): the refresh request is a JSON body with `client_id`, `grant_type=refresh_token`, `refresh_token` and `scope=openid profile email`; the response carries `id_token`, `access_token` and `refresh_token`. Unverified: the docs publish no request limit and no rate-limit header for this endpoint.

- [Codex device login](https://github.com/openai/codex/blob/rust-v0.165.0/codex-rs/login/src/device_code_auth.rs), [OAuth client](https://github.com/openai/codex/blob/rust-v0.165.0/codex-rs/login/src/oauth/client.rs), and [token exchange](https://github.com/openai/codex/blob/rust-v0.165.0/codex-rs/login/src/server.rs): device endpoints and form-encoded authorization code exchange. These endpoints are not a separately documented public API.
