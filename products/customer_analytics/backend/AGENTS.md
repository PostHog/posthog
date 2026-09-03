# Customer analytics — backend

## Access control: account reads are project-wide, mutations remain gated

Every project member can read accounts and their account-owned metadata. Account access-control rows do not hide account records, custom property values, relationships, notes, or other account read surfaces.

- Account-scoped viewsets set `access_control_unrestricted_read = True`. Read-only POST query actions list themselves in `access_control_unrestricted_read_actions`. `AccessControlPermission` still checks project membership, while scoped API tokens still need the corresponding `account:read` scope.
- Read facades use team-scoped account querysets without `UserAccessControl` filtering.
- Account HogQL tables are unscoped, like `system.groups`. Project query contexts, including shared links and userless jobs, can read them.
- A related resource with its own access model still enforces it. For example, account communication endpoints separately check the `ticket` resource, and warehouse-backed account tabs check warehouse access.

Account mutations remain access-controlled:

- `AccessControlViewSetMixin` + `scope_object = "account"` requires `editor` for create, update, and other non-safe actions.
- `_AccountDestructiveActionPermission` additionally requires effective project admin access for deletes and destructive actions such as ending a relationship.
- Direct account update and delete paths enforce object-level editor access.
- Nested account mutations use `facade.get_writable_account_id(...)`. Create viewsets set `access_control_allow_specific_create = True` only when this target check runs before the write. This keeps a caller with only a specific account grant from mutating a different account.
- A caller with resource-level `editor` can mutate nested resources for any account in the project. This is the accepted model for account-owned custom properties, relationships, notebooks, and similar children.

When adding an account surface, use `get_readable_account_id(...)` for reads and `get_writable_account_id(...)` for mutations. Do not reintroduce account filtering on list or detail reads. Preserve any independent access check for data owned by another resource.
