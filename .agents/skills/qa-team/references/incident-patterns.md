# Incident Patterns Reference

Synthesized failure patterns from production incidents.
This document grounds QA review agents with real-world failure modes.

## Pattern 1: Database Migration Failures

**Common triggers:**

- `AddIndexConcurrently` mixed with `AddField` in a single `atomic=False` migration
- Server-side cursors holding long transactions that block `CREATE INDEX CONCURRENTLY`
- Schema changes on tables shared with external services (e.g., a Django table also written to by a Rust or Go service)
- Migration analyzers not recognizing product-scoped app labels, bypassing safety checks
- Duplicate database records from inconsistent `app_label` declarations

**Review signals:**

- Any migration file mixing DDL operations (AddField + AddIndex) in one migration
- Migrations touching tables that multiple services write to
- `atomic = False` without clear justification
- `AddIndexConcurrently` on tables with known long-running queries
- Missing `SeparateDatabaseAndState` for complex schema changes

## Pattern 2: Hot-Path Service Fragility

**Common triggers:**

- Database connection timeouts reduced without load testing
- Retry amplification without circuit breakers
- Shared Redis between critical services and the main application (cross-service blast radius)
- Unbounded cache population from Postgres to Redis on cache misses
- Kubernetes pods undersized, causing CPU saturation >90%
- Rate limiting seeing all traffic as a single IP behind a load balancer
- Outlier accounts with extreme data volumes causing OOM on cache rebuild tasks
- Deployment race conditions between controllers (e.g., ArgoCD Application vs ApplicationSet)
- Cross-language serialization bugs when both old and new field names exist in cached data

**Review signals:**

- Any change to hot-path evaluation, serialization, or caching logic
- Timeout/retry configuration changes
- Helm chart or deployment value refactors affecting service selectors
- Cross-language serialization boundaries (e.g., Python cache -> Rust reader)
- Changes to background task memory patterns (unbounded data loading)

## Pattern 3: SDK Backwards Compatibility Breaks

**Common triggers:**

- SDK extension calls a function only available in newer core SDK versions
- Lazy-loaded CDN extensions always serve latest version against a pinned older core SDK
- Fetch/XHR wrappers not passing through all request options (e.g., duplex, FormData)
- Multiple fix attempts without stepping back to understand the full scope of the issue
- CDN publishing with manual approval steps that get missed — fixes never deploy
- No SDK-side error monitoring; detection relies on support tickets

**Review signals:**

- Any change to SDK extension code that references core SDK APIs
- Changes to fetch/XHR wrappers or request interception
- CDN vs npm version synchronization
- Missing feature flags for high-risk SDK changes
- Absence of integration tests across SDK version combinations

## Pattern 4: Security & Data Exposure

**Common triggers:**

- CI/CD workflow misconfiguration allowing arbitrary code execution from external PRs
- Security tool warnings dismissed without deep analysis
- Service account tokens with overly broad permissions
- Content publicly accessible via API regardless of access control rules
- Cache invalidation not propagating disable/delete actions to public-facing endpoints
- Outbound HTTP requests to user-supplied URLs without SSRF protection (domain blocklist, redirect validation)
- Loose dependency version constraints (`>=` instead of `==`)

**Review signals:**

- Any CI/CD workflow change, especially trigger events
- API endpoints returning data without authentication
- Changes to public/unauthenticated endpoint responses
- Code making outbound requests to user-controlled URLs
- Dependency version constraint changes
- Token/key permission scopes

## Pattern 5: Performance & Resource Exhaustion

**Common triggers:**

- Database materialized view insert amplification (1 insert triggering hundreds of real inserts)
- Coordination service saturation (e.g., Zookeeper hitting outstanding request limits)
- Untagged database queries running as default user, invisible to resource management
- Missing configuration for insert delay/backpressure (unlimited part creation)
- Background tasks loading entire datasets into memory without batching or streaming
- Pod CPU saturation from undersized nodes
- Connection pool exhaustion from expensive TLS handshakes during pool initialization
- Django admin inline or `ModelAdmin` gaining a new `ForeignKey` without a matching `autocomplete_fields`, `raw_id_fields`, or `readonly_fields` entry — every change-page render fires a default `<select>` populated from the entire target table, per row

**Review signals:**

- New database queries without observability tags
- Queries scanning unbounded date ranges
- Background tasks loading data proportional to customer volume
- Missing pagination/streaming in data processing
- Resource request/limit changes in Kubernetes manifests
- New materialized views or insert-time transformations
- New `ForeignKey`/`OneToOneField` added to a model whose existing `admin.StackedInline` / `admin.TabularInline` / `ModelAdmin` classes don't list the field in `autocomplete_fields`, `raw_id_fields`, or `readonly_fields` — review every inline variant of the same model across parent admins, not just the one mentioned in the PR description

## Pattern 6: Data Correctness & Silent Failures

**Common triggers:**

- Database compatibility mode or config changes breaking aggregation logic silently
- Experimental database features silently deleting data in production
- Cache updates failing silently, causing stale data to be served indefinitely
- Misleading metrics (e.g., pods in crash-loop backoff not generating OOM events during idle periods)

**Review signals:**

- Database version or compatibility setting changes
- Experimental database features enabled in production configs
- Any change to data aggregation or date/time handling queries
- Cache update mechanisms without freshness verification
- Monitoring that only covers hot/recent data, not historical data integrity

## Pattern 7: Infrastructure & Deployment Failures

**Common triggers:**

- Configuration refactors creating non-atomic changes across multiple files
- Default values that fail silently (e.g., a selector matching zero pods)
- Infrastructure migrations (networking, CNI, service mesh) breaking specific services in production despite passing in dev/staging
- Revert PRs that don't actually restore service health
- Hardcoded configuration requiring a full deploy cycle to change
- Deployment rollback failing due to permission misconfiguration
- Missing alerts for customer-facing services (multi-hour detection gaps)

**Review signals:**

- Deployment configuration file restructuring
- Default values that silently degrade (match nothing, return empty)
- Infrastructure changes to networking, CNI, service mesh
- Config values that should be runtime-adjustable but are hardcoded
- Missing alerting for new services or endpoints

## Pattern 8: Cross-Service & Queue Processing Failures

**Common triggers:**

- Jobs consumed from one backend but routed to another due to missing configuration mapping
- Janitor/cleanup processes resetting "stalled" jobs without retry limits, causing duplicate execution
- Customer-facing side effects (emails, notifications) without idempotency guards
- Job queues growing to many times normal size without backpressure mechanisms

**Review signals:**

- Job queue producer/consumer configuration changes
- Background job processing without idempotency keys
- Missing retry caps or deduplication in queue processors
- Side-effect-producing code (email, notification, webhook) without idempotency
- Task queue configuration changes

## Pattern 9: Frontend & UX Papercuts

These are recurring UX failure patterns synthesized from internal papercut reports.
They represent the most common classes of user-facing issues that ship to production.

**Common triggers:**

- **Generic/unhelpful error messages** — API returns a specific validation error but the UI
  shows "A server error occurred" or a blanket permission error. Users get no guidance on
  what went wrong or how to fix it. "Get Help" links redirect to forums instead of filing
  a support ticket.
- **Missing feedback on click actions** — Clicking a button produces no visible response:
  no spinner, no state change, no confirmation. Destructive actions (delete, remove)
  execute immediately without a confirmation modal.
- **Content overflow and layout breakage** — Long text overflows containers instead of
  wrapping. UI clips on smaller viewports. Scroll-to targets don't account for fixed
  headers, landing users at the wrong position.
- **Stale or non-reactive UI state** — Feature flag values not updating after load
  (component not reactive to async flag changes). State lost when switching tabs.
  Cached data served after config changes without a freshness check.
- **Ambiguous visual states** — Toggle switches, dropdowns, and inputs look the same
  whether active/inactive or filled/empty. Placeholder text indistinguishable from
  real input. Different entity types (events vs actions) not visually distinct in pickers.
- **Inconsistent UI patterns across features** — Search/filter UIs differ per product area.
  Some trim whitespace, some don't. Some search display names, some only search keys.
  Some require minimum character counts without telling the user.
- **UI restructuring leaving stale references** — Moving a panel or renaming a setting
  breaks in-app cross-links, documentation screenshots, and help text. Users follow
  instructions to locations that no longer exist.
- **Misleading or confusing text** — Date formats that prioritize less-useful information
  (e.g., "first seen" before "last seen"), error messages with internal jargon
  ("premium PostHog offering"), copy that doesn't match the actual product behavior.
- **Non-selectable or non-copyable text** — Error messages in tooltips that disappear on
  hover-off. Text rendered on canvas elements that can't be selected. JSON values that
  include surrounding quotes when copied.
- **Input method (IME) conflicts** — Enter key used for both character confirmation
  (CJK input) and form submission, making the product unusable for East Asian users.

**Review signals:**

- New error messages that don't tell users what to do next
- Click handlers without loading indicators or optimistic UI updates
- Destructive actions (delete, remove) without confirmation dialogs
- Dynamic content rendered without overflow/wrapping constraints
- Components that read feature flags without reactive hooks
- Text inputs or search fields with ad-hoc filtering instead of shared utilities
- UI changes that move or rename elements without updating cross-references
- User-facing copy with internal terminology or ambiguous wording
- Text rendered in non-selectable contexts (canvas, tooltip, SVG)
- Form submission handlers that don't handle IME composition events

---

## Cross-Cutting Anti-Patterns

1. **Unbounded operations** — retries, cache population, data loading, connection creation without limits
2. **Fail-silent defaults** — values that match nothing, operations that silently skip, missing error propagation
3. **Client-side-only filtering** — relying on UI/SDK targeting instead of server-side access control
4. **Single-service testing of multi-service changes** — testing only the changed service, not downstream consumers
5. **Manual deployment steps** — approval gates, CDN publishing, cache warming that humans forget
6. **Environment asymmetry** — configuration differences between regions/environments causing incidents in only one
7. **Shared infrastructure without isolation** — databases, caches, and queues shared across services without resource limits
8. **Monitoring blind spots** — missing coverage for CPU, storage internals, cold data integrity, queue backlogs
