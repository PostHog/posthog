# Feature flag API writes

Ordinary feature flag POST, PUT, and PATCH requests enter `facade.api.create_flag` or `facade.api.update_flag` through `FeatureFlagViewSet.create` and `FeatureFlagViewSet.update`.
The viewset retains authentication, API scopes, project scoping, object permissions, approval exception handling, and response serialization.
It passes the original request and serializer context to the facade, including PUT versus partial-update semantics.

The facade uses `FeatureFlagSerializer` as the existing v1 write adapter.
Each write validates and saves once.
The serializer owns request validation, approvals, persistence, tags, evaluation contexts, audit history, analytics, and cache side effects.
The facade's serializer dependency is legacy; this path does not establish a pattern for new facade contracts or product isolation.

Stored configurations with an absent `filters.version` or a numeric value equal to 1 use v1 validation.
Other stored formats fail with `unsupported_config_version` before v1 normalization, including updates that omit filters or supply `{}`.
Every incoming `filters.version`, including numeric 1, still fails with `reserved_config_version`.
Supplied top-level v1 filter keys replace those keys in the stored state; `{}` retains targeting and `groups: []` clears it.
The existing validation rollout controls normalization and unknown-key preservation.

Dependency targets must also use v1 configurations.
The dependency validator resolves IDs within the existing project scope, rejects disabled targets, and checks `filters.version` before accepting an edge.
During the cycle walk, reference resolution checks each target's format before reading its v1 properties, including reachable targets without `groups`.
A rejected format returns `unsupported_dependency_config_version` at `filters`, identifying the target by ID without including its configuration.
The check adds no database queries to the existing person-condition dependency walk.

Group-only conditions and writes that re-enable a flag or restore an active deleted flag also check reachable target formats, independently of structural-validation rollout settings.
This supplementary traversal fetches pending targets in batches of at most 100 IDs and visits each ID once, without scanning the whole project.
This check does not enable group dependencies: their existing aggregation validation still applies.
Metadata-only and empty-filter updates retain their existing no-op targeting semantics unless they make stored targeting usable again.
Restoring a deleted flag that stays disabled does not require repairing its dependencies.
Disabling, archival, and deletion retain their existing dependent-flag protections.

| Source configuration | Target configuration                      | Write behavior                                      |
| -------------------- | ----------------------------------------- | --------------------------------------------------- |
| V1                   | Absent version, numeric 1, or numeric 1.0 | Existing dependency validation                      |
| V1                   | Numeric 2 or 2.0                          | Reject the dependency                               |
| V1                   | Null, string, boolean, or another version | Reject the dependency                               |
| V2                   | Any flag dependency                       | Unsupported by the dormant validator; no write path |

The row's `FeatureFlag.version` remains an independent concurrency counter.
Conversion attempts remain blocked by incoming-version rejection and the stored-format write guard.
A future converter must reject conversion of a target with inbound v1 dependencies before changing its configuration format.

Do not wrap facade writes in an outer transaction.
An approval-required write creates a pending change request and then raises; an outer transaction would roll that request back.
The serializer's existing update transaction locks the flag and increments its row version.
Its other effects retain their existing placement outside that transaction.

Service callers retain their request shims, actor attribution, and system-write behavior.
Facade updates reload stored encrypted payloads before returning a model for reuse.
Both HTTP write adapters apply the existing authentication-dependent payload renderer: personal API keys receive plaintext and other authentication receives a redacted placeholder.
Empty-filter updates preserve the stored ciphertext without encrypting it again.

A rollback restores ordinary HTTP routing to the previous serializer path.
Keep any format rejection or reader capability required by configuration data that exists at rollback time.
In particular, retain v1-to-v2 dependency protection once v2 targets can exist; rollback does not convert stored configurations to v1.

## Config version 2 updates (closed)

`facade.config_writes.V2_UPDATE_LIMITS` is the writer policy for config version 2 updates.
It is `None` in every deployed configuration, so no entrypoint — HTTP, facade, system write, direct serializer, or approval replay — can accept a v2 write, and the behavior described above is the only behavior production has.
Before any production v2 row can exist, including an inactive row, the common safety gate must establish that deployed readers and dependent write paths can handle it safely.
The closed policy does not establish that safety; a trusted per-team admission policy must replace it before writes open.
Admission also requires an agreed production byte limit for each rule's opaque `metadata` object and matching configuration-size limits in writers and readers.
The metadata limit has no production value yet, so `V2_UPDATE_LIMITS` remains `None`.

When the policy admits updates, a stored v2 row that is not remote-configured and carries no encrypted payloads takes a separate path:

- A supplied `filters` object replaces the whole configuration. There is no top-level merge, no rule merge by index, no filling of omitted fields from the stored document, and no v1 normalization. `{}`, `null`, a list, and an incomplete object are invalid; a complete document with `rules: []` is valid.
- A PATCH that omits `filters` updates `name`, `key`, and `tags` without rewriting the stored configuration. Every other field, including activation, archival, deletion, remote config, and payload fields, is rejected with `unsupported_config_version`.
- Rule IDs and percentage-rollout seeds are server-owned and identify rules rather than list positions. An echoed ID keeps its seed through reordering and unrelated edits; a rule that omits its ID is new and receives fresh identity. An unknown ID, an ID used twice, a client-chosen seed, and a changed seed are all rejected.
- `FeatureFlag.version` is required and must equal the locked row's value. Unlike v1 there is no `original_flag` merge: a stale token is a conflict even when no individual field clashes, because the document replaces everything. The token applies to metadata-only updates too.
- Identity resolution and validation both run against the locked row inside the existing update transaction, so warnings describe the real before/proposed pair. A stored document with an unsupported shape or semantics is rejected rather than replaced. Configuration and metadata byte limits apply to the replacement, so an oversized stored document can be edited back under a lowered limit.
- Request bytes that repeat a JSON key are rejected before normalization can hide the duplicate. Non-finite numbers and percentages with more than two decimal places are rejected by the validator itself.
- An enabled flag-write approval policy denies the update, and an approved change cannot be applied to a v2 row: PH-WRITE-APPROVAL owns that path. Nothing here creates a pending v2 change request.
  The final policy lookup and flag mutation share an organization-scoped transaction lock with policy creation and updates, so a policy cannot be enabled between that lookup and commit.
  Flag writes take the lock in shared mode so different flags can update concurrently; policy writes take it in exclusive mode.

Rollback closes the policy and reverts the update routing. Format guards and readers stay in place for whatever data exists at that point; there is no automatic v2-to-v1 conversion, and v1-to-v2 dependency protection is not removed.
