# Account detail presence

Account detail pages show avatars for other active teammates who can read the same account.

The browser sends `POST /api/projects/:team_id/accounts/:account_id/presence/` when the page opens and every 30 seconds while the tab is visible. The request has no body. The server derives the viewer identity from the authenticated user.

Each heartbeat updates an account-scoped Redis roster. A viewer expires after 90 seconds without another heartbeat. Hidden tabs and unmounted pages stop heartbeats, so another viewer can remain visible for up to 90 seconds after leaving.

The response contains only other active viewers. Each viewer has a `user_id` and `display_name`. The response does not include email addresses. Duplicate tabs from one user appear as one viewer.

The endpoint requires `account:read` and returns 404 when the caller cannot read the account. Service credentials receive an empty list and do not create presence. Redis errors also return an empty list, so presence cannot prevent the account page from loading.

The frontend sequences heartbeat responses. A late response cannot replace newer viewer data.
