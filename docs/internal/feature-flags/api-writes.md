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
