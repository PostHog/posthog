# API behavior verification checklist

Before finalizing endpoint logic, verify from docs **and** with curl against the live API (not just docs — APIs frequently silently ignore unknown params or document outdated enums):

- Response shape: list vs object vs wrapped data (`{"data": [...]}`).
- Pagination: Link header vs body cursor vs offset/page; how next-page termination is signaled.
- Ordering guarantees: ascending/descending/undefined for time fields, and the API's _default_ sort if you don't pass one. If you paginate with a cursor (`before`/`after` tokens), confirm whether the API allows `sort` and time-window params alongside it — many reject or ignore them, which dictates both your `sort_mode` and how pagination terminates on incremental syncs.
- **Primary key uniqueness scope:** is the id unique globally, or only within its parent resource? For fan-out children, assume per-parent unless the docs say otherwise and put the parent id in the composite key.
- **Sort enum per endpoint:** which `sorting=` values does each list endpoint accept? Some APIs vary the allowed enum per resource. Confirm with curl that the value you intend to pass returns 200, and probe with a future-date cutoff to confirm whether timestamp filters are honored or silently ignored.
- **Server-side timestamp filter:** does `<field>_gte` / `since` / `modified_after` actually filter, or does the API accept it and ignore it? Test by passing a future date and checking whether the row drops out.
- Rate-limit headers (window reset timestamp, concurrent limits).
- Field stability: whether candidate incremental/partition fields can change over time.

If undocumented, keep parsing/merge logic conservative and add a short code comment noting the uncertainty.
