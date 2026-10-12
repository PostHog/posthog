# Authz

## OpenFGA model

`model.fga` and `openfga_model.json` are generated. Never edit them by hand.
Edit the sources in `model/`, then run `products/authz/generate_model.sh`.
The pre-commit hook runs the same script when a commit touches `model/` or `model.fga`, and `tests/test_model_builder.py` runs the checks in CI.

- `model/core.fga`: the hand-written core types: users, organizations, members, roles, projects, access policies and resource categories.
- `model/resource.fga`: the template that every resource type copies.
- `model/resources.toml`: one entry for each access-controlled resource type.
- `model/limits.toml`: the agreed size of each core type and the agreed exceptions to the rules. The checks fail when the model and this file differ.

### Before you change the model

Use the first option that works:

1. **Add a resource.** Add an empty `[<resource_type>]` table to `resources.toml`. The name must be a `ResourceType` value. Most resources need nothing more.
2. **Put request-time rules in the SDK, not the model.** Plan checks, level limits, owner rules, URL resolution and legacy behavior stay in Python.
3. **Add a relation to one resource.** Give it a `why`, and raise that resource's number in `limits.toml`. Use `but not`, `and` or a `type:*` wildcard only with an entry in `[complex_resource_relations]`.
4. **Change the core or the template.** This changes every resource. Raise the `limits.toml` numbers in the same diff, and expect the reviewer to question each one.

A new permission (`can_<action>`) needs a matching `Action` in `backend/facade/enums.py`, or the SDK cannot call it.
Every relation must feed a permission or an SDK `Level`.
Every permission a resource adds or replaces needs a true and a false check in `model.fga.yaml`.
