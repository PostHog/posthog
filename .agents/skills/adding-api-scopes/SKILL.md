---
name: adding-api-scopes
description: 'Guidance for adding an API scope object to posthog/scopes.py and making it work for personal API keys, OAuth tokens and MCP clients. Use when adding a scope object, exposing a viewset or MCP tool to tokens, moving a viewset off scope_object = "INTERNAL", deciding if a scope is internal, OAuth-hidden or privileged, choosing a scope group, reading the scope list in Python, the frontend or the MCP server, or when a scope test fails in scopes.test.ts, test_scopes.py or tool-filtering.test.ts. Trigger terms: new scope, APIScopeObject, ScopeObjectEnumApi, scope_object, required_scopes, API_SCOPES, API_SCOPE_GROUPS, mcp scopes, OAuth scopes, personal API key scope.'
---

# Adding an API scope

A scope has two parts: an object and an action, as in `feature_flag:read`.
Adding a scope means adding a scope object, such as `feature_flag`. It gives tokens `feature_flag:read` and `feature_flag:write`.
`posthog/scopes.py` is the source of the object list.
The frontend type and the MCP OAuth list are generated from it.
Each object a picker offers also has a `ScopeDoc`: its name, plural, one-sentence description, group, docs link, the levels a picker offers, whether it reaches the whole organization, and any scope its writes also need.
The owning product declares it in `products/<name>/backend/scopes.py`, and core objects are in `CORE_SCOPE_DOCS` in `posthog/scope_docs.py`.
The web app's `API_SCOPES` and `API_SCOPE_GROUPS` are built from those declarations, so the frontend keeps no copy.

## Decide if you need a new scope

Most endpoints fit an existing scope, for example `insight:read`.
Add a new scope only for a product area that a person wants to grant or withhold on its own, on a key or an OAuth app.
Name its object with a `snake_case` singular noun, such as `feature_flag`.

## Decide what kind of scope it is

- **Public:** OAuth lists it, MCP can request it, and the key picker offers it. This is the default.
- **Internal:** only the server creates tokens with it. Use `INTERNAL_API_SCOPE_OBJECTS`.
- **OAuth-hidden:** a person can paste it into a personal API key, but OAuth clients do not see it. Use this for staff-only or unreleased surfaces. Use `OAUTH_HIDDEN_SCOPE_OBJECTS`.
- **Privileged:** only PostHog staff can give it to an OAuth app, through Django admin or a data migration. An app that registers itself cannot get it, and the CLI login and the key picker presets never include it. Use this for a scope that a partner app must not grant to itself, such as `llm_gateway`. Use `PRIVILEGED_SCOPES`. The picker row reads it from the generated scope docs.

Then decide two more things, separately from the kind:

- **Project secret API keys:** a project secret API key is a project credential with no user, for server-to-server calls. Allow the scope on it only when such a caller needs it. The allowed list is `PROJECT_SECRET_API_KEY_ALLOWED_API_SCOPE_ACTION`, in both `posthog/scopes.py` and `frontend/src/lib/scopes.tsx`. Read `/adding-project-secret-api-key-auth` first.
- **Access control:** if an organization must be able to restrict the resource per role or per object, add it to `ACCESS_CONTROL_RESOURCES` in `products/access_control/backend/facade/user_access_control.py`. Access control resources use scope object names by design, so a viewset's `scope_object` names both its token scope and its access control resource. Do not give access control a naming or a type of its own. The `resource` fields of the access control serializers take `GRANTABLE_API_SCOPE_OBJECTS` as their choices, and the frontend `APIScopeObject` type is generated from those fields (be careful: the personal API key modal, the OAuth consent screen, CLI login and the key presets also use that type).

## To add the scope

1. **Declare it in Python.** Add the object to the `APIScopeObject` literal in `posthog/scopes.py`. If you chose internal, OAuth-hidden or privileged above, also add it to that set.
   - Add the same value to `ResourceType` in `products/authorization/backend/facade/enums.py`. The shared permission check names the scope with that type, so a scope without one returns a 500 on its endpoints.
2. **Connect it to its endpoints.** Set `scope_object = "<object>"` on each viewset the scope covers.
   - Standard actions need no extra work: `list` and `retrieve` need `:read`, and `create`, `update` and `destroy` need `:write`.
   - A custom `@action` needs `required_scopes`, for example `required_scopes=["<object>:write"]`. Use `:read` if it only reads data, and `:write` if it changes data. Without it, token requests get a 403.
   - An endpoint set to `scope_object = "INTERNAL"` accepts only logged-in sessions. Change it to the new object to open it to tokens.
   - Then call each custom action with a personal API key that has only the new scope. No test checks this.
3. **Regenerate.** Run `hogli build:openapi`, which carries the object to the frontend type, and `hogli build:projections`, which updates the OAuth lists of the MCP server and the web app. **DO NOT EDIT GENERATED FILES BY HAND.**
4. **Explain it.** Skip this step for an OAuth-hidden object: no picker shows it, and the tests do not ask for a doc or a group.
   - Add a `ScopeDoc` to `SCOPE_DOCS` in `products/<name>/backend/scopes.py`, or to `CORE_SCOPE_DOCS` for a core object. Give it a sentence-case name, a plural that is lowercase except for proper nouns and acronyms, and one sentence under 120 characters on what the scope covers, without "read" or "write" (`/writing-user-facing-copy`). Link the product's page under `https://posthog.com/docs/` when one exists. Pick its `group` (see "Choose a group"). Set `actions=("read",)` if no endpoint writes, and `organization_wide=True` if it reaches past one project. If writing it also writes another object, as a survey writes its targeting flag, set `write_requires` to that scope and the reason.
   - If no picker should offer the object, add a reason to `SCOPE_OBJECTS_OMITTED_FROM_PICKERS` in `posthog/scopes.py` instead.
   - Run `hogli build:projections` again to regenerate `frontend/src/lib/scopeDocs.generated.ts`.
5. **Let MCP tools request it.** For each MCP tool that calls the endpoint, add the scope under `scopes:` in `products/<product>/mcp/tools.yaml`.

## Choose a group

The OAuth consent screen and the scope pickers show objects in groups, from the `group` of each `ScopeDoc`. The groups and their order are the `ScopeGroup` literal in `posthog/scope_docs.py`.
The groups make a long list readable, so a person can find a product quickly.

- A group is a product area that a person recognizes, such as "Session replay" or "Feature flags, experiments & surveys". It is not a code module or a team.
- Put the object in the existing group that a person would look in first.
- Add a new group to `ScopeGroup` only when it gets two or more objects. A group with one object makes the list longer, not easier to read.

## If a test fails

- **`posthog/test/repo_invariants/test_scope_docs.py`:** an exposed object has no `ScopeDoc`, or a `ScopeDoc` names an object that is hidden or omitted from pickers. Add the doc, or the omission reason, as in step 4. A `ValueError` at import names a `ScopeDoc` with a missing field, a long description, a dash, a docs link outside posthog.com/docs, an unknown group, or a `write_requires` that names an unknown scope.
- **`posthog/test/test_scopes.py`:** an internal, OAuth-hidden or privileged scope leaks into a list it must stay out of, or the project secret API key list in `posthog/scopes.py` differs from the copy in `frontend/src/lib/scopes.tsx`. Fix the set, or make the two lists equal.
- **`posthog/test/repo_invariants/test_api_scopes_have_resource_types.py`:** a scope has no `ResourceType`. Add one, as step 1 says.
- **`services/mcp/tests/unit/tool-filtering.test.ts`, the completeness test:** an MCP tool requires a scope that OAuth does not advertise. If the scope is new, run `hogli build:projections`. If it is internal, add it to the test's server-only list. Otherwise fix the scope name in `tools.yaml`.

## What no test covers

- A custom `@action` without `required_scopes`. Tokens get a 403.
- A read scope on an action that changes data.
- An MCP tool scope that differs from its endpoint's `scope_object`.
- A group that makes no sense for the object, or a new group that should not exist. `ScopeDoc` only checks that the group exists. Check that the object sits where a person would look for it, and that a new group has at least two objects. See "Choose a group".
- A wrong or unclear name or description.

## Where to read scopes in code

Use these instead of writing your own list of scopes.

- **Python:** import from `posthog.scopes`.
  - `API_SCOPE_OBJECTS`: every object, internal ones too.
  - `GRANTABLE_API_SCOPE_OBJECTS`: the objects a person can grant.
  - `ALL_SCOPES`: the grantable `object:action` strings.
  - `get_oauth_scopes_supported()`: what the OAuth server advertises.
- **Frontend type:** `APIScopeObject` from `~/types`.
- **Frontend list at runtime:** `Object.values(ScopeObjectEnumApi)`, from `products/access_control/frontend/generated/api.schemas`.
- **Python names and descriptions:** `get_scope_docs()` from `posthog.scope_docs`.
- **Frontend labels and groups:** `API_SCOPES`, `API_SCOPE_GROUPS` and `getScopeDescription` from `lib/scopes`.
- **OAuth lists:** `OAUTH_SCOPES_SUPPORTED` and `OAUTH_SCOPES_HIDDEN`, from `lib/oauthScopes.generated` in the web app and `services/mcp/src/lib/oauth-scopes.generated.ts` in the MCP server. The two files are the same.
