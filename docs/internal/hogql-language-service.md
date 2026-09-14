# HogQL language service

## Goal

The HogQL language service moves latency-sensitive SQL editor operations into a long-lived Go process. Its resident
catalog avoids rebuilding tables, views, and property metadata for every keystroke.

The service targets:

- low-single-digit-millisecond autocomplete on a warm catalog;
- a stable internal API for HogQL validation and, later, translation; and
- low PostHog overhead above ClickHouse execution time.

## Architecture

```text
Browser
  | authenticated PostHog request
  v
Django
  | resolves team membership and user permissions
  | publishes visible catalog with a scoped service JWT
  v
HogQL language service
  | selects the exact team and user catalog
  | parses and resolves entirely in memory
  v
Autocomplete or validation response
```

Django remains authoritative for authentication, team membership, entitlements, feature flags, and access-control
resolution. The Go service does not read PostHog permission tables or accept browser-selected identity without an
authenticated internal request.

## Isolation boundary

Every protected route requires both `team_id` and `user_id` in its path. Shared middleware converts those values into
one authorization struct used by JWT verification, rate limiting, catalog lookup, and request handlers.

The service keys its current catalog cache by that pair because the published snapshot contains user-filtered tables
and properties.

The transport JWT also binds the request to:

- one positive team ID;
- one positive user ID;
- one service audience;
- an explicit operation; and
- a short validity window.

An absent, invalid, expired, or evicted catalog fails closed. The service never falls back to another team or user's
catalog.

Before reading a request body, a bounded token bucket limits the direct peer address. After JWT verification, another
bounded bucket limits the authenticated team and user pair. The service ignores forwarded-IP headers because only
deployment infrastructure can define a trustworthy proxy chain.

A later implementation may store structural schema once per team and apply smaller user authorization overlays. The
team remains the primary isolation boundary in that model.

## Resident state

Catalog publication replaces the catalog and revision atomically. Readers observe either the previous complete
revision or the next complete revision.

The in-memory registry has two bounds:

- an idle TTL removes unused entries; and
- least-recently-used eviction caps the number of entries.

Warm autocomplete and validation perform no synchronous metadata requests. Catalog refresh remains outside the
keystroke path.

## API direction

The initial internal API supports:

- publishing and deleting a catalog for one team and user;
- contextual autocomplete with at most 25 results and cursor pagination; and
- syntax and catalog-backed semantic validation.

Responses return the catalog revision used for computation. Callers can discard results produced from a stale
revision.

HogQL translation is the next service capability. Its stable response should contain parameterized ClickHouse SQL,
bound values, referenced resources, output schema, warnings, and catalog revisions. The internal parser AST is not an
API contract.

## Deployment and rollout

The production container builds a static binary with Go 1.27.1 and runs as a non-root user. A non-loopback listener
fails startup unless dedicated signing keys are configured.

Local and debug environments may use the service directly. Production integration remains behind a server-side
feature flag and should progress through shadow comparison before serving editor results.

The initial rollout keeps ClickHouse execution in Django:

```text
Django -> language service translation -> Django -> ClickHouse
```

Measurements must separate catalog lookup, parsing, translation, network transit, ClickHouse duration, result
decoding, and serialization. A combined translation and execution path is justified only if the extra service hop
prevents the overhead target.

## Non-goals

- Reimplementing PostHog membership or permission resolution in Go.
- Exposing the language service directly to browsers.
- Treating feature flags as an authorization boundary.
- Moving ClickHouse execution before latency measurements justify it.
- Making the parser's internal AST a compatibility contract.
