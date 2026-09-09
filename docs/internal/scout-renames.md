# Scout rename limits

The scout rename endpoint preserves configuration, skill versions, owners, source links, runs, targeted notes, and the scout's own memories in one transaction. Memories move for both namespaces the scout keys on its name: its follow-up queue and its self-improvement suggestions.

Each rename can move up to 10,000 rows from each history table: runs, targeted notes, and memories across both namespaces. The endpoint reads at most 10,001 identifiers per table before it writes. It rejects a larger history with `400` and leaves the scout unchanged. Updates use the selected identifiers, so a concurrent insert cannot increase the size of an update.

The endpoint permits five rename requests per canonical project per hour under the standard API rate limiter. Users, API credentials, and child environments share the limit. A throttled response uses `429` and includes `Retry-After`.

The row limit remains active even when API rate limiting is disabled. It prevents an editor from repeatedly rewriting an unlimited run history. This endpoint does not start a background rename. Support for larger histories requires a separate design that uses stable identity or bounded background work.
