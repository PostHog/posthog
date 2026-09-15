# Google Workspace egress

## Identity

The connected Google account's OAuth `sub`, under the key `google_workspace:account:<sub>`, because Gmail and Calendar meter quota per user per project.
A caller with no account in scope, such as the Google OAuth diagnostics in `ee/api/google_oauth_diagnostics.py`, passes no scope and records volume only.

## Budget

Read from settings at acquire time:

- `GOOGLE_WORKSPACE_EGRESS_PER_MINUTE_BUDGET` (default 250)
- `GOOGLE_WORKSPACE_EGRESS_HOURLY_BUDGET` (default 10,000)

[Gmail allows](https://developers.google.com/workspace/gmail/api/reference/quota) 6,000 quota units per user per minute, and `users.messages.get` costs 20 units, so 250 requests a minute stays under Google's limit even when every call is a message fetch.
[Calendar allows](https://developers.google.com/workspace/calendar/api/guides/quota) 600 requests per user per minute.

## Lanes and callers

The policy is **flat** (`reserve={}`), and `google_workspace_request` defaults to `BATCH`.
Every scoped caller is a background sync:

- Gmail sync, `products/conversations/backend/services/gmail_sync.py`
- Calendar sync, `products/customer_analytics/backend/logic/calendar_sync.py`

No higher lane needs headroom, and the default ladder would deny the syncs at 70% of a budget that already sits close to Google's own limit.
Add the ladder back if an interactive caller starts using this domain.

## Rate-limit headers

Google documents no rate-limit headers. [A quota error](https://developers.google.com/workspace/gmail/api/guides/handle-errors) is a 403 or 429 with a reason such as `rateLimitExceeded` in the JSON body, so the domain declares no gauges.
The counter is `google_workspace_api_requests_total`, labeled `scope, method, endpoint, status_code, source`.

## Auth

The caller passes the account's OAuth access token, sent as a bearer token.

## Sources

- [Gmail usage limits](https://developers.google.com/workspace/gmail/api/reference/quota): quota units per user and per method.
- [Calendar quotas](https://developers.google.com/workspace/calendar/api/guides/quota): requests per user per minute.
- [Gmail errors](https://developers.google.com/workspace/gmail/api/guides/handle-errors): quota errors in the response body.
