# GitLab egress

Calls to the GitLab REST API (`/api/v4`) on gitlab.com and on self-managed instances.

## Identity

A hash of the instance host and the access token, built by `token_scope` in `transport.py`.
GitLab meters authenticated API traffic per user, and each token belongs to one user (a bot user for project and group access tokens).
The token is a secret and the scope is a metric label, so both parts go through `scope_fingerprint`.
A user with several tokens shows as several scopes. GitLab does not tell us the user id without an extra call.

## Budget

None: calls are recorded, never gated (`RecordedEgressClient`).
The customer owns the token on their own GitLab account or instance.
The admin of each self-managed instance sets its limits, and gitlab.com limits depend on the plan, so PostHog has no single limit to stay under.
Callers honor a `429` and its `Retry-After`.
Add a gate if one token starts to carry enough PostHog traffic to reach the gitlab.com limit.

## Lanes and callers

No lanes, because nothing is gated.
`posthog/models/integration/gitlab.py` is the caller, with `source="integration"`.
It creates, closes and searches issues, lists project members, lists projects and creates and reads merge requests.
Error tracking code search in `products/error_tracking/backend/presentation/views/git_provider_file_link_resolver.py` still calls GitLab directly and has not moved here yet.

## Rate-limit headers

GitLab sends these on every response, throttled or not:

- `RateLimit-Limit` feeds `gitlab_api_rate_limit_limit`.
- `RateLimit-Remaining` feeds `gitlab_api_rate_limit_remaining`.
- `RateLimit-Reset`, a Unix timestamp, feeds `gitlab_api_rate_limit_reset_timestamp_seconds`.
- `RateLimit-Name`, the throttle that applies, is the `resource` label. A value outside GitLab's documented throttle names records as `unknown`, because a self-managed instance controls the header.

The headers show only the most restrictive Rack::Attack throttle.
Application limits, such as issue creation, can answer `429` while the headers still show quota.
Throttled responses from the Projects, Groups and Users APIs carry no informational headers.
The counter is `gitlab_api_requests_total`, labeled `scope, method, endpoint, status_code, source`.
Callers pass an endpoint template, because a project path in a URL is customer data.

## Auth

The customer's access token in the `PRIVATE-TOKEN` header.
No PostHog-owned credential.
The caller validates the host before the call and never follows a redirect, because the token header would go to the redirect target.

## Sources

- [GitLab.com rate limits](https://docs.gitlab.com/user/gitlab_com/rate_limits/): authenticated API traffic for a user is limited per minute, plan-based limits are proposed, and all responses carry `RateLimit-Limit` and `RateLimit-Remaining` except throttled responses from the Projects, Groups and Users APIs.
- [User and IP rate limits, response headers](https://docs.gitlab.com/administration/settings/user_and_ip_rate_limits/#response-headers): `RateLimit-Limit`, `RateLimit-Name`, `RateLimit-Observed`, `RateLimit-Remaining`, `RateLimit-Reset` as Unix time, and `RateLimit-ResetTime` and `Retry-After` on a `429`. Only the most restrictive Rack::Attack limit appears.
- [Rate limits](https://docs.gitlab.com/rate_limits/): self-managed admins set most limits in the Admin area.
