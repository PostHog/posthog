# WorkOS Radar egress

## Identity

WorkOS meters the Radar API per API key, and an instance holds a single Radar key (`WORKOS_RADAR_API_KEY`).
The whole instance draws from one budget under the key `workos_radar:api_key:default`.

## Budget

WorkOS allows 1,000 requests per 60 seconds per API key on `/radar/*`, shared by attempts and list operations.
That limit applies on top of the general limit of 6,000 requests per 60 seconds per API key.
WorkOS documents no hourly limit, so the policy has one 60-second window.

- `WORKOS_RADAR_EGRESS_PER_MINUTE_BUDGET` (default 800) stays under the WorkOS limit.
  The gap leaves room for list calls from the WorkOS dashboard and for clock drift between our window and theirs.

When Redis is down, each process gets a quarter of the budget (`in_memory_divider=4`).

## Lanes and callers

The default reserve applies, so `BATCH` is shed at 70% of the window and `NORMAL` at 90%.
`workos_radar_request` has no default lane, so every caller states one.
All callers are in `posthog/workos_radar.py`:

| Call                                    | Source           | Lane     | When the limiter sheds it                                         |
| --------------------------------------- | ---------------- | -------- | ----------------------------------------------------------------- |
| `POST /radar/attempts` for a signup     | `signup`         | `NORMAL` | The check records an `error` verdict and the signup goes through. |
| `POST /radar/attempts` for a login      | `login`          | `NORMAL` | The check records an `error` verdict and the login goes through.  |
| `PUT /radar/attempts/:id` after success | `success_report` | `BATCH`  | The Celery task retries the report later.                         |

A shed check lets the attempt through, which is what a WorkOS 429 or a timeout already did.
Nothing runs `CRITICAL`, because every call carries an address that someone typed.

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
