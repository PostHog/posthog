# Authz

## OpenFGA model

The files in `generated/` (`model.fga` and `openfga_model.json`) are generated. Never edit them by hand.
Edit the sources in `model/`, then run `products/authz/generate_model.sh`.
The script builds the model, checks the model rules and runs the OpenFGA tests.
The pre-commit hook runs it when a commit touches `model/` or `generated/`, and `tests/test_model_builder.py` runs the rule checks in CI.

A resource is all objects of one type in a project, such as the dashboards in project 3 (`resource:<org_id>/3/dashboard`).
An object is one item, such as dashboard 12 (`dashboard:<org_id>/3/12`).

- `model/core.fga`: the hand-written core types: users, organizations, members, roles, projects, access policies and resources.
- `model/object.fga`: the bases that object types extend, such as `object` and `shareable_object`.
- `model/resources/<resource_type>.fga`: the object type of one resource type in each file. The file name and the type name are a `ResourceType` value.
- `model/core.fga.yaml` and `model/resources/<resource_type>.fga.yaml`: the OpenFGA tests for the core and for each resource type.
- `model/fixtures.yaml`: the core tuples that every test file loads.

### Resource files

A resource file holds one object type. Most extend a base:

```text
type dashboard extends shareable_object
  relations
    # Why the object type needs this relation.
    define legacy_editor: creator or ((member from project) but not restricted)
    # Why the object type changes this permission.
    override can_edit: editor and legacy_editor
    # Why the object type drops this permission.
    remove can_share
```

- `define` adds a relation. It cannot reuse a name that the base defines.
- `override` replaces an inherited permission (`can_*`), and `remove` drops one.
- The stored relations and the `viewer`, `editor` and `manager` levels stay as the base defines them.
- Each extension `define`, `override` and `remove` needs a comment above it that says why.
- A resource with different scope resolution can declare a standalone type without `extends`. It defines its own relations and permissions; normal model validation and test requirements still apply.

### Before you change the model

Use the first option that works:

1. **Add a resource type.** Add `resources/<resource_type>.fga` with an empty `relations` block, and its test file.
2. **Put request-time rules in the SDK, not the model.** Plan checks, level limits, owner rules, URL resolution and legacy behavior stay in Python.
3. **Change one resource type.** Add relations to its file, or override or remove its permissions.
4. **Change the core or a base.** This changes every object type that uses it, so expect the reviewer to question it.

A permission in a resource file needs a matching `Action` in `backend/facade/enums.py`, or the SDK cannot call it.
Every relation must feed a permission or an SDK `Level`.

### Tests

Every model change needs OpenFGA tests in the same diff, in the test file of the type it changes:

- Every permission, including each inherited permission of a new resource type, has a check that expects `true` and a check that expects `false`.
- Every stored relation (a relation with a `[type]` restriction) appears in at least one test tuple.
- The tests pass. `generate_model.sh` runs `fga model test`, so the pre-commit hook fails when a test fails.
