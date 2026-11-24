# WorkOS Radar egress

## Identity

WorkOS meters the Radar API per API key, and an instance holds a single Radar key (`WORKOS_RADAR_API_KEY`).
The report budget uses the key `workos_radar:api_key:default`.

## Budget

WorkOS allows 1,000 requests per 60 seconds per API key on `/radar/*`, shared by attempts and list operations.
That limit applies on top of the general limit of 6,000 requests per 60 seconds per API key.

Only the success reports draw from a budget:

- `WORKOS_RADAR_REPORT_EGRESS_PER_MINUTE_BUDGET` (default 300) caps the success reports.
  The checks can use the remaining 700 requests per minute.
- A value under 1 counts as 1, so a bad setting slows the reports but never stops them.
- When Redis is down, each process admits one report a minute (`in_memory_divider` equals the budget), because no process knows how many others run. The shed reports retry, up to 24 times.

The checks have no budget on purpose.
A shed check lets the attempt through, so a gated check would let a flood of logins turn Radar off for every signup.
An ungated check also keeps the login path free of limiter calls to Redis.
A flood that passes the ingress throttles reaches the WorkOS limit and gets a 429, which lets the attempt through, as before this domain existed.

## Lanes and callers

The reports are the only gated caller, so the policy is flat (`reserve={}`).
All callers are in `posthog/workos_radar.py`:

| Call                                    | Helper                | Source           | Gate                                                           |
| --------------------------------------- | --------------------- | ---------------- | -------------------------------------------------------------- |
| `POST /radar/attempts` for a signup     | `workos_radar_check`  | `signup`         | None. Recorded only.                                           |
| `POST /radar/attempts` for a login      | `workos_radar_check`  | `login`          | None. Recorded only.                                           |
| `PUT /radar/attempts/:id` after success | `workos_radar_report` | `success_report` | `BATCH`. A shed report raises, and the Celery task retries it. |

## Rate-limit headers

WorkOS documents no rate-limit status headers, so the domain declares no gauges.
A 429 can carry `Retry-After`, and the success report task waits for it.
The counter is `workos_radar_api_requests_total`, labeled `api_key, method, endpoint, status_code, source`.
The `endpoint` label is `attempts` or `attempts/:id`, so attempt IDs never become label values.

## Auth

`WORKOS_RADAR_API_KEY` authenticates every call as a bearer token.
`posthog/workos_radar.py` makes no call while `WORKOS_RADAR_ENABLED` is off or the key is empty.

## Sources

- [Rate limits](https://workos.com/docs/reference/rate-limits): 1,000 requests per 60 seconds per API key on `/radar/*`, the general limit of 6,000 per 60 seconds per API key, the 429 status, and `Retry-After` on some 429 responses. The page names no other rate-limit header.
- [Radar attempts](https://workos.com/docs/reference/radar/attempts): the attempts endpoints. The page states no limit of its own.
