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
