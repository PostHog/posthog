# HogQL system table cache permissions

Query cache keys must account for every permission scope that can change the result.
A cache hit returns before schema resolution and table predicates run.
`queried_access_controlled_resources` collects these scopes before the query runner builds its cache key.

Tables with an `access_scope` contribute that scope directly.
Hidden tables whose predicates read scoped parents contribute those parents through `_TRANSITIVE_SYSTEM_TABLE_SCOPES`.
This includes the account tag and notebook junctions, ticket tag and assignment junctions, and ticket assignee roles.
The cache fingerprint includes resource denials, object denials, object grants, and the caller identity needed for creator exemptions.

Keep row filtering on the parent when a junction already uses a predicate such as `account_id IN (SELECT id FROM system.accounts)`.
That predicate applies the parent's team and object permissions, including its creator exemption.
Adding a separate object-ID filter to the junction can hide child rows that the parent permits its creator to read.

When adding a hidden system table, declare its direct or transitive cache scope and test the resulting cache key under different permissions.
Also verify that its predicates deny unauthorized reads and preserve object grants and creator exemptions.
Userless data-modeling queries must resolve the parent through `DATA_MODELING_ALLOWED_SYSTEM_TABLES`; a transitive cache entry does not grant access.
