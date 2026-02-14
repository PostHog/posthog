# Pagination for the Endpoints Product `/run` Route

## Current State

The `/run` route today supports a `limit` parameter (HogQL queries only), but has **no offset, no `hasMore` indicator, and no way to page through results**. Clients get a truncated result set with no signal that more data exists.

Two execution paths exist:

- **Materialized**: Builds a `SELECT * FROM saved_table` AST — adding OFFSET here is trivial
- **Inline HogQL**: Parses the SQL and sets `parsed.limit` — same story, OFFSET can be added alongside
- **Insight queries** (Trends, Funnels, etc.): Return small aggregated payloads — pagination doesn't apply and shouldn't be offered

## The Core Constraint

The endpoints product intentionally limits flexibility compared to `/query`. Pagination should be:

- Simple for the API consumer (good DX)
- Impossible to misuse
- Not expose internal query machinery

---

## Option 1: Offset-based with `hasMore` (Simple & Transparent)

**Request adds**: `offset: int` (default 0)
**Response adds**: `hasMore: bool`, `limit: int`, `offset: int`

```text
POST /run
{"limit": 100, "offset": 0}

→ {"results": [...100 rows...], "hasMore": true, "limit": 100, "offset": 0}

POST /run
{"limit": 100, "offset": 100}

→ {"results": [...73 rows...], "hasMore": false, "limit": 100, "offset": 100}
```

**Implementation**: Use the `LIMIT N+1` trick — request 101 rows internally, return 100, set `hasMore = len(raw) > limit`. Add `ast.Constant(value=offset)` to the parsed AST for both materialized and inline paths.

**Pros**:

- Dead simple — every developer already knows offset pagination
- Zero new concepts
- Works identically for GET and POST (offset/limit can be query params or body)
- No server-side state
- Minimal code change (add offset to AST, add hasMore to response)

**Cons**:

- Large offsets are inefficient in ClickHouse (OFFSET 100000 still scans 100000 rows)
- Results can shift between pages if underlying data changes (acceptable for endpoints since data is cached/materialized)

---

## Option 2: Opaque Cursor with `next` URL (Best DX)

**Request adds**: `cursor: str | None` (opaque token, replaces offset/limit on subsequent requests)
**Response adds**: `next: str | null` (full URL to fetch next page)

```text
POST /run
{"limit": 100}

→ {
    "results": [...100 rows...],
    "next": "/api/environments/123/endpoints/my-data/run?cursor=eyJvIjoxMDAsImwiOjEwMH0"
  }

GET /api/environments/123/endpoints/my-data/run?cursor=eyJvIjoxMDAsImwiOjEwMH0

→ {
    "results": [...73 rows...],
    "next": null
  }
```

The cursor is a base64-encoded JSON payload containing `{offset, limit, variables_hash}`. The server owns the format — clients never construct cursors, they just follow the `next` URL.

**Implementation**: First request uses limit+1 trick. If more rows exist, encode state into cursor and build a `next` URL. Subsequent requests decode cursor, validate, and execute with encoded offset/limit. The run route already accepts GET, so `next` URLs work as simple GET requests — no need to re-POST the body.

**Pros**:

- Best developer experience — "just follow `next`"
- Server controls the pagination strategy entirely (can switch to keyset later without breaking clients)
- Cursor can embed a `variables_hash` to detect when parameters changed mid-pagination
- Pagination via GET means no need to re-send request body
- Familiar pattern (GitHub API, Stripe API, Slack API all do this)

**Cons**:

- Slightly more implementation complexity than raw offset
- Cursor is opaque — harder to debug ("why did I get page 3?")
- Cursor encodes offset internally, so same ClickHouse efficiency concern (but can be migrated to keyset without API change)

---

## Option 3: Cache-Windowed Pagination (Outside the Box)

**Key insight**: Endpoints already cache query results. Pagination can be a _view into the cached result set_ rather than re-executing the query.

**How it works**:

1. First `/run` request: execute query with NO limit, cache the full result set under a cache key, return the first page + a `result_id`
2. Subsequent requests: `GET /run?result_id=abc&offset=200&limit=100` — reads from cache, slices to the requested window

```text
POST /run
{"limit": 100}

→ {
    "results": [...100 rows...],
    "result_id": "ep_abc123",
    "total_count": 5432,
    "hasMore": true
  }

GET /run?result_id=ep_abc123&offset=100&limit=100

→ {
    "results": [...100 rows...],
    "result_id": "ep_abc123",
    "total_count": 5432,
    "hasMore": true
  }
```

**Implementation**: After query execution, store full results in Django cache (or Redis) with a TTL matching `cache_age_seconds`. The `result_id` is the cache key. Subsequent requests bypass query execution entirely — just slice `cached_results[offset:offset+limit]`.

**Pros**:

- Pages 2+ are nearly free — no ClickHouse query at all
- Consistent results across all pages (same result set)
- `total_count` is available for free since we have all results
- Natural fit with endpoints' existing caching infrastructure
- Random access — can jump to any page, not just sequential
- Could even support insight queries (cache the aggregated result, paginate the series)

**Cons**:

- First request is slower (fetches all data, not just one page)
- Memory pressure — full result sets in cache
- TTL expiration means pagination can "expire" mid-session
- Requires a result size cap to prevent unbounded memory usage
- More moving parts than pure offset

---

## Option 4: Hybrid — Offset-based + Auto-Caching (Pragmatic Middle Ground)

Combine Options 1 and 3: use offset-based parameters, but have the server **opportunistically cache** the full result set on first execution.

**Request**: `{"limit": 100, "offset": 0}`
**Response**: `{"results": [...], "hasMore": true, "limit": 100, "offset": 0}`

Under the hood:

- If the query is materialized → use SQL OFFSET (always fast against S3 table)
- If the query is inline and `offset == 0` → execute with no limit, cache full results, return first page
- If the query is inline and `offset > 0` → check cache first; if hit, slice from cache; if miss, fall back to SQL OFFSET

The client doesn't know or care about the caching. The API is simple offset+limit. But in practice, pagination is fast because results are cached.

**Pros**:

- Simple API surface (just offset + limit + hasMore)
- Fast in practice (cached after first hit)
- Gracefully degrades if cache misses (falls back to SQL OFFSET)
- No new concepts for the API consumer
- Materialized endpoints don't even need caching (SQL OFFSET on S3 table is fine)

**Cons**:

- Implementation complexity is hidden but still exists
- Cache management adds code
- Inconsistency: sometimes you get cached results, sometimes fresh — though this already happens with the existing cache layer

---

## Recommendation

**Option 2 (Opaque Cursor)** is the best fit for the endpoints product.

**Why**:

1. **Matches the product philosophy**: Endpoints limit flexibility. An opaque cursor is the ultimate expression of that — the server controls pagination, clients just follow links. There's nothing to misconfigure.

2. **Best DX**: The `next` URL pattern is what developers expect from modern APIs. No offset math, no off-by-one bugs, no "what happens if I set offset to -1" edge cases.

3. **Future-proof**: The cursor format is internal. Today it encodes an offset. Tomorrow it could encode a keyset, a cache pointer, or a result_id — all without changing the API contract. This is important because materialized endpoints (fast S3 tables) and inline endpoints (ClickHouse queries) may want different strategies.

4. **GET-based follow-up**: The first request is POST with variables/filters. But the `next` URL is a GET — all state is in the cursor. This means pagination doesn't require re-sending the request body, which is a significant DX win.

5. **Scope**: Only applies to HogQL queries. Insight queries return aggregated data that doesn't paginate. The implementation can reject cursor + insight query combinations cleanly.

### Implementation steps

1. Add `cursor` field to `EndpointRunRequest` schema
2. Add `next` and `hasMore` fields to the run response
3. Create `EndpointCursor` dataclass: `{offset, limit, version, variables_hash}`
4. In `_execute_materialized_endpoint`: add `ast.Offset` to the SELECT AST, request limit+1 rows
5. In `_execute_inline_endpoint` / `_apply_limit_to_query`: add OFFSET to parsed HogQL, request limit+1 rows
6. In `_execute_query_and_respond`: trim results to limit, compute `hasMore`, build `next` URL if hasMore
7. In `run()`: if cursor is present, decode it and use its offset/limit/version instead of request body values
8. Validate: reject cursor for non-HogQL queries, reject cursor with mismatched variables_hash
9. Add `offset` to OpenAPI spec generation
10. Update frontend to display pagination info in the endpoint test panel
