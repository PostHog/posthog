# Brevo (v3) endpoint inventory

Base URL: `https://api.brevo.com/v3`
Auth: `api-key` request header (account-wide API key).
Pagination: `limit` + `offset` (offset is a record index, not a page number — confirmed via the
official `getbrevo/brevo-python` SDK docs).
Sorting: every list endpoint only sorts by **record creation date** via `sort=asc|desc` (default `desc`).
We always request `sort=asc` for stable pagination boundaries and monotonic `createdAt` ordering.

| Schema             | Path                 | Array key   | Page size | Incremental                      | Partition key |
| ------------------ | -------------------- | ----------- | --------- | -------------------------------- | ------------- |
| `contacts`         | `/contacts`          | `contacts`  | 1000      | `createdSince` / `modifiedSince` | `createdAt`   |
| `contact_lists`    | `/contacts/lists`    | `lists`     | 50        | — (full refresh)                 | —             |
| `contact_folders`  | `/contacts/folders`  | `folders`   | 50        | — (full refresh)                 | —             |
| `contact_segments` | `/contacts/segments` | `segments`  | 50        | — (full refresh)                 | —             |
| `email_campaigns`  | `/emailCampaigns`    | `campaigns` | 100       | — (full refresh)                 | `createdAt`   |
| `sms_campaigns`    | `/smsCampaigns`      | `campaigns` | 100       | — (full refresh)                 | `createdAt`   |
| `email_templates`  | `/smtp/templates`    | `templates` | 100       | — (full refresh)                 | —             |
| `senders`          | `/senders`           | `senders`   | n/a       | — (full refresh, single request) | —             |

## Incremental notes

Only `/contacts` exposes genuine server-side timestamp filters (`createdSince`, `modifiedSince`,
both `YYYY-MM-DDTHH:mm:ss.SSSZ`). All other list endpoints accept `sort` but no `*Since` filter, so
they ship as full refresh. `email_campaigns` has `startDate`/`endDate`, but they only filter _sent_
campaigns by send date — not a general modification cursor — so it stays full refresh.

`/contacts` sorts by creation date only. With `sort=asc` a `createdAt` cursor is strictly monotonic.
A `modifiedAt` cursor is not strictly ordered within a page, but the source is resumable on `offset`,
so a crashed sync resumes mid-stream rather than re-deriving its position from the watermark — the
per-batch watermark commit therefore can't skip rows in practice.

## Rate limits

Brevo enforces tight per-endpoint limits (≈10 req/s on `/contacts`, ≈100 req/hour on most others).
We retry `429`/`5xx` with exponential backoff + jitter (`tenacity`, 5 attempts). Large page sizes
keep request counts low (a 100k-contact account is ~100 requests at `limit=1000`).

## Not yet verified against the live API

Endpoint behavior was sourced from the current public docs and the official `getbrevo/brevo-python`
SDK; it was **not** smoke-tested with curl because no API key was available in the build environment.
The response array keys and field names are taken from the SDK model definitions and should be
re-confirmed against a real account before promoting past `alpha`.
