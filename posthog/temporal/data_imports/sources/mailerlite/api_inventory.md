# MailerLite API inventory

Base URL: `https://connect.mailerlite.com/api` (current date-versioned API, released 2022-03-22).
Auth: `Authorization: Bearer <api-key>` (account-wide API key; the simple API-key model has no
granular per-resource scopes). `Accept: application/json`.

## Verified with curl (2026-06-02)

Without a live key only auth behavior and endpoint existence were verifiable:

- `GET /subscribers` with no/invalid token → `401 {"message":"Unauthenticated."}`.
- All endpoints below return `401` (not `404`) for an invalid token, confirming the paths exist.

The response **shapes, pagination cursors, and field names below are taken from the public API
docs** and could not be exercised against live data without credentials. Parsing is kept
conservative (follow `links.next`, yield rows verbatim, merge on `id`).

## Endpoints implemented

| Schema          | Path             | Pagination  | Primary key | Partition key |
| --------------- | ---------------- | ----------- | ----------- | ------------- |
| subscribers     | /subscribers     | cursor      | id          | created_at    |
| campaigns       | /campaigns       | page number | id          | created_at    |
| groups          | /groups          | page number | id          | created_at    |
| segments        | /segments        | page number | id          | created_at    |
| fields          | /fields          | page number | id          | (none)        |
| automations     | /automations     | page number | id          | created_at    |
| forms_popup     | /forms/popup     | page number | id          | created_at    |
| forms_embedded  | /forms/embedded  | page number | id          | created_at    |
| forms_promotion | /forms/promotion | page number | id          | created_at    |
| webhooks        | /webhooks        | page number | id          | created_at    |

## Pagination

All list endpoints wrap rows in `{"data": [...], "links": {...}, "meta": {...}}`. Both the
cursor-based `subscribers` endpoint and the page-number endpoints expose an absolute next-page URL
at `links.next` (or `null` on the last page), so a single "follow `links.next`" loop covers both.
Page size capped at 100 (default 25); we request `limit=100`.

## Incremental sync

None. The current API exposes **no server-side timestamp filter** (`updated_after`, `since`, etc.)
on any list endpoint — `created_at` / `updated_at` are returned in responses but cannot be filtered
on. A client-side cursor would still page through the entire collection every run, so per the
warehouse-source guidance every endpoint ships **full refresh only** (`supports_incremental=False`).
This matches the Airbyte MailerLite connector, which is also full-refresh only.

Pagination is still resumable (the source is a `ResumableSource`): the next-page URL is persisted to
Redis after each page so Temporal can resume mid-collection after a heartbeat timeout.

## Rate limits

120 requests/minute globally (5/minute for bulk import/upsert, which this source does not use).
`429` responses are retried with exponential backoff via `tenacity`.
