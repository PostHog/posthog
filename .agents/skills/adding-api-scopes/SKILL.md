---
name: adding-api-scopes
description: 'Guidance for adding an API scope object to posthog/scopes.py and making it work for personal API keys, OAuth tokens and MCP clients. Use when adding a scope object, exposing a viewset or MCP tool to tokens, moving a viewset off scope_object = "INTERNAL", deciding if a scope is internal, OAuth-hidden or privileged, choosing a scope group, reading the scope list in Python, the frontend or the MCP server, or when a scope test fails in scopes.test.ts, test_scopes.py or tool-filtering.test.ts. Trigger terms: new scope, APIScopeObject, ScopeObjectEnumApi, scope_object, required_scopes, API_SCOPES, API_SCOPE_GROUPS, mcp scopes, OAuth scopes, personal API key scope.'
---

# Adding an API scope

A scope has two parts: an object and an action, as in `feature_flag:read`.
Adding a scope means adding a scope object, such as `feature_flag`. It gives tokens `feature_flag:read` and `feature_flag:write`.
`posthog/scopes.py` is the source of the object list.
The frontend type and the MCP OAuth list are generated from it.
The picker rows and the groups are kept by hand in `frontend/src/lib/scopes.tsx`, and a test checks them.
They stay in the frontend on purpose: labels, plurals, groups and picker omissions are UI decisions, while `posthog/scopes.py` decides what exists and what it grants.

## Decide if you need a new scope

Most endpoints fit an existing scope, for example `insight:read`.
Add a new scope only for a product area that a person wants to grant or withhold on its own, on a key or an OAuth app.
Name its object with a `snake_case` singular noun, such as `feature_flag`.

## Decide what kind of scope it is

- **Public:** OAuth lists it, MCP can request it, and the key picker offers it. This is the default.
- **Internal:** only the server creates tokens with it. Use `INTERNAL_API_SCOPE_OBJECTS`.
- **OAuth-hidden:** a person can paste it into a personal API key, but OAuth clients do not see it. Use this for staff-only or unreleased surfaces. Use `OAUTH_HIDDEN_SCOPE_OBJECTS`.
- **Privileged:** only PostHog staff can give it to an OAuth app, through Django admin or a data migration. An app that registers itself cannot get it, and the CLI login and the key picker presets never include it. Use this for a scope that a partner app must not grant to itself, such as `llm_gateway`. Use `PRIVILEGED_SCOPES`, and set `unprivilegedExcluded: true` on the picker row.

Then decide two more things, separately from the kind:

- **Project secret API keys:** a project secret API key is a project credential with no user, for server-to-server calls. Allow the scope on it only when such a caller needs it. The allowed list is `PROJECT_SECRET_API_KEY_ALLOWED_API_SCOPE_ACTION`, in both `posthog/scopes.py` and `frontend/src/lib/scopes.tsx`. Read `/adding-project-secret-api-key-auth` first.
- **Access control:** if an organization must be able to restrict the resource per role or per object, add it to `ACCESS_CONTROL_RESOURCES` in `products/access_control/backend/facade/user_access_control.py`. Access control resources use scope object names by design, so a viewset's `scope_object` names both its token scope and its access control resource. Do not give access control a naming or a type of its own. The `resource` fields of the access control serializers take `GRANTABLE_API_SCOPE_OBJECTS` as their choices, and the frontend `APIScopeObject` type is generated from those fields (be careful: the personal API key modal, the OAuth consent screen, CLI login and the key presets also use that type).

## To add the scope

1. **Declare it in Python.** Add the object to the `APIScopeObject` literal in `posthog/scopes.py`. If you chose internal, OAuth-hidden or privileged above, also add it to that set.
2. **Connect it to its endpoints.** Set `scope_object = "<object>"` on each viewset the scope covers.
   - Standard actions need no extra work: `list` and `retrieve` need `:read`, and `create`, `update` and `destroy` need `:write`.
   - A custom `@action` needs `required_scopes`, for example `required_scopes=["<object>:write"]`. Use `:read` if it only reads data, and `:write` if it changes data. Without it, token requests get a 403.
   - An endpoint set to `scope_object = "INTERNAL"` accepts only logged-in sessions. Change it to the new object to open it to tokens.
   - Then call each custom action with a personal API key that has only the new scope. No test checks this.
3. **Regenerate.** Run `hogli build:openapi`, which carries the object to the frontend type, and `hogli build:projections`, which updates the MCP OAuth list. **DO NOT EDIT GENERATED FILES BY HAND.**
4. **Show it in the pickers.** In `frontend/src/lib/scopes.tsx`:
   - Add a row to `API_SCOPES` with a sentence-case label and plural (`/writing-user-facing-copy`). Disable `write` if no endpoint writes. If the key modal should not offer the object, add a reason to `API_SCOPES_OMITTED_FROM_MODAL` instead.
   - Add the object to one group in `API_SCOPE_GROUPS`. See "Choose a group".
5. **Let MCP tools request it.** For each MCP tool that calls the endpoint, add the scope under `scopes:` in `products/<product>/mcp/tools.yaml`.

## Choose a group

The OAuth consent screen and the scope pickers show objects in groups, from `API_SCOPE_GROUPS` in `frontend/src/lib/scopes.tsx`.
The groups make a long list readable, so a person can find a product quickly.

- A group is a product area that a person recognizes, such as "Session replay" or "Feature flags, experiments & surveys". It is not a code module or a team.
- Put the object in the existing group that a person would look in first.
- Add a new group only when it gets two or more objects. A group with one object makes the list longer, not easier to read.
- OAuth-hidden objects go in "Internal tools". The pickers do not show these objects, so a person never sees this group. Do not put a public object there, because it would show under the "Internal tools" label.

## If a test fails

- **`frontend/src/lib/scopes.test.ts`, the coverage test:** a grantable object has no picker row and no omission reason. Add a row to `API_SCOPES`, or a reason to `API_SCOPES_OMITTED_FROM_MODAL`. If the object is missing from `APIScopeObject`, run `hogli build:openapi` first.
- **`frontend/src/lib/scopes.test.ts`, the group test:** an object is in no group, or in two groups. Put it in exactly one group of `API_SCOPE_GROUPS`.
- **`posthog/test/test_scopes.py`:** an internal, OAuth-hidden or privileged scope leaks into a list it must stay out of, or the project secret API key list in `posthog/scopes.py` differs from the copy in `frontend/src/lib/scopes.tsx`. Fix the set, or make the two lists equal.
- **`services/mcp/tests/unit/tool-filtering.test.ts`, the completeness test:** an MCP tool requires a scope that OAuth does not advertise. If the scope is new, run `hogli build:projections`. If it is internal, add it to the test's server-only list. Otherwise fix the scope name in `tools.yaml`.

## What no test covers

- A custom `@action` without `required_scopes`. Tokens get a 403.
- A read scope on an action that changes data.
- A group that makes no sense for the object, or a new group that should not exist. The group test only checks that each object has exactly one group. Check that it sits where a person would look for it, and that a new group has at least two objects. See "Choose a group".
- A wrong or unclear label.

## Where to read scopes in code

Use these instead of writing your own list of scopes.

- **Python:** import from `posthog.scopes`.
  - `API_SCOPE_OBJECTS`: every object, internal ones too.
  - `GRANTABLE_API_SCOPE_OBJECTS`: the objects a person can grant.
  - `ALL_SCOPES`: the grantable `object:action` strings.
  - `get_oauth_scopes_supported()`: what the OAuth server advertises.
- **Frontend type:** `APIScopeObject` from `~/types`.
- **Frontend list at runtime:** `Object.values(ScopeObjectEnumApi)`, from `products/access_control/frontend/generated/api.schemas`.
- **Frontend labels and groups:** `API_SCOPES`, `API_SCOPE_GROUPS` and `getScopeDescription` from `lib/scopes`.
- **MCP server:** `OAUTH_SCOPES_SUPPORTED` and `OAUTH_SCOPES_HIDDEN` from `services/mcp/src/lib/oauth-scopes.generated.ts`.
