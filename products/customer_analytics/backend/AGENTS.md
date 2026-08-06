# Customer analytics — backend

## Access control: accounts and their sub-resources are resource-level scoped

Account viewsets and their nested sub-resources (custom property values, notebooks, and
future account children) authorize at the **resource level**, not the object level:

- `AccessControlViewSetMixin` + `scope_object = "account"` enforces the caller's default
  access to the `account` scope (`viewer` for reads, `editor` for writes) plus project
  membership.
- `facade.get_accessible_account_id(...)` additionally filters to accounts the caller can
  see (effective access above `none`).

Per-account **object-level** access overrides are intentionally **not** enforced on writes
to nested sub-resources. A caller with resource-level `editor` can therefore write the
sub-resources of any account they can see, even if their access to that specific account
was lowered to `viewer`. This is the accepted model for now — keep new account
sub-resource viewsets consistent with it: gate on `get_accessible_account_id` and rely on
the mixin for the resource-level `editor` requirement.

Automated security reviewers periodically flag nested account write endpoints as an
"object-level write access bypass". That is **known and intentional** here — don't treat it
as a bug to fix. If we later decide to enforce object-level writes, mirror the account
update/delete path: call `_enforce_object_access(account, user_access_control, "editor")`
in the nested viewset's `create`/`destroy` before the write.
