# Feature flag API writes

Ordinary feature flag POST, PUT, and PATCH requests enter `facade.api.create_flag` or `facade.api.update_flag` through `FeatureFlagViewSet.create` and `FeatureFlagViewSet.update`.
The viewset retains authentication, API scopes, project scoping, object permissions, approval exception handling, and response serialization.
It passes the original request and serializer context to the facade, including PUT versus partial-update semantics.

The facade uses `FeatureFlagSerializer` as the existing v1 write adapter.
Each write validates and saves once.
The serializer owns request validation, approvals, persistence, tags, evaluation contexts, audit history, analytics, and cache side effects.
The facade's serializer dependency is legacy; this path does not establish a pattern for new facade contracts or product isolation.

Stored configurations with an absent `filters.version` or a numeric value equal to 1 use v1 validation.
Other stored formats fail with `unsupported_config_version` before v1 normalization, including updates that omit filters or supply `{}`; stored version 2 rows take the separate path described under "Config version 2 writes".
Every incoming `filters.version`, including numeric 1, still fails with `reserved_config_version`, except a version 2 document sent to a project the writer policy admits.
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

| Source configuration | Target configuration                      | Write behavior                      |
| -------------------- | ----------------------------------------- | ----------------------------------- |
| V1                   | Absent version, numeric 1, or numeric 1.0 | Existing dependency validation      |
| V1                   | Numeric 2 or 2.0                          | Reject the dependency               |
| V1                   | Null, string, boolean, or another version | Reject the dependency               |
| V2                   | Any flag dependency                       | Rejected by the strict v2 validator |

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

## Config version 2 writes

Two internal feature flags form the writer policy, evaluated by `facade.config_writes` for the `project` group (targeted by project `id`) with local evaluation only, so an unresolved flag reads as off:

- `feature-flag-rules-v2-writes`: the projects whose flags may be created, updated and enabled with config version 2.
- `feature-flag-rules-v2-creation`: whether an admitted project may create a new version 2 flag. Turning it off leaves existing rows updatable, enableable and disableable.

Nothing else grants admission: no request field, serializer context flag, staff status, internal team or missing user.
`FEATURE_FLAG_RULES_V2_MAX_METADATA_BYTES` bounds one rule's opaque `metadata` object in an admitted write; the default is pilot scope and is revisited before users author documents through the editor or broader API use.
The deployment filter-size limit (`MAX_FEATURE_FLAG_FILTER_SIZE_BYTES`) bounds the whole document, as it does for v1.

| Operation                                 | Requires                                                                        | Closed                                                                                                  |
| ----------------------------------------- | ------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| Create (`POST` with `filters.version` 2)  | Admitted project, creation enabled, no `active: true`                           | Every other project keeps `reserved_config_version`; `active: true` is rejected rather than downgraded  |
| Full-document update (`filters`)          | Admitted project, current `version`                                             |                                                                                                         |
| Metadata update (`name`, `key`, `tags`)   | Admitted project, current `version`                                             | Every other field, including `archived`, remote config and payload fields                               |
| Enable (`active: true`)                   | Admitted project, current `version`, stored document valid under current limits |                                                                                                         |
| Disable (`active: false`)                 | Current `version` only                                                          | An enabled flag-write approval policy, like every other row here                                        |
| Delete (`deleted: true`, the soft delete) | Current `version` only; disables an enabled row in the same write               | Restore (`deleted: false`); the separate `archived` field and the `/archive/` action; an enabled policy |

A stored version 2 row that is not remote-configured and carries no encrypted payloads always takes this path, whatever its project: disabling and soft-deleting are the pilot's incident controls and do not depend on either writer flag.

- A new row is created disabled with server-owned rule IDs and seeds; the request document is resolved against an empty stored document and validated strictly before it is persisted exactly. No v1 row is converted.
- A supplied `filters` object replaces the whole configuration. There is no top-level merge, no rule merge by index, no filling of omitted fields from the stored document, and no v1 normalization. `{}`, `null`, a list, and an incomplete object are invalid; a complete document with `rules: []` is valid.
- Rule IDs and percentage-rollout seeds are server-owned and identify rules rather than list positions. An echoed ID keeps its seed through reordering and unrelated edits; a rule that omits its ID is new and receives fresh identity. An unknown ID, an ID used twice, a client-chosen seed, and a changed seed are all rejected.
- `FeatureFlag.version` is required on every update and must equal the locked row's value. Unlike v1 there is no `original_flag` merge: a stale token is a conflict even when no individual field clashes. The token applies to disabling and deleting too.
- Identity resolution, validation and the enable check run against the locked row inside the existing update transaction. A stored document with an unsupported shape or semantics is rejected rather than replaced or enabled. Configuration and metadata byte limits apply to a replacement, so an oversized stored document can be edited back under a lowered limit; enabling requires the stored document to fit the current limits.
- Request bytes that repeat a JSON key are rejected before normalization can hide the duplicate. Non-finite numbers and percentages with more than two decimal places are rejected by the validator itself.
- An enabled flag-write approval policy (`feature_flag.enable`, `feature_flag.disable` or `feature_flag.update`, on the team or its organization) denies every version 2 write, disable and delete included, and an approved change cannot be applied to a version 2 row: PH-WRITE-APPROVAL owns that path. Nothing here creates a pending change request; to disable a version 2 flag under such a policy, disable the policy first.
  The final policy lookup and flag mutation share an organization-scoped transaction lock with policy creation and updates, so a policy cannot be enabled between that lookup and commit.
  Flag writes take the lock in shared mode so different flags can update concurrently; policy writes take it in exclusive mode.
- Each accepted write saves once, increments `version` once, runs the existing cache invalidation and produces one activity log entry through the existing receiver. The entry carries the generic field diff; canonical version 2 summaries and version-history reconstruction are later work.

Rollback turns both flags off. Existing version 2 rows stay readable, disableable and deletable; there is no data conversion, and v1-to-v2 dependency protection is not removed.
