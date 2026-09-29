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

## Add the object

- `posthog/scopes.py`: the `APIScopeObject` literal, and the lists you chose above.
- The viewset: `scope_object`. Default actions map to read or write. A custom `@action` needs `required_scopes`, or tokens get a 403. Use `:read` for an action that only reads data, and `:write` for an action that changes data. `scope_object = "INTERNAL"` keeps an endpoint session-only.
- `frontend/src/lib/scopes.tsx`:
  - a row in `API_SCOPES`, or a reason in `API_SCOPES_OMITTED_FROM_MODAL`. Labels are user-facing, so use sentence case (`/writing-user-facing-copy`). Disable `write` if the viewset has no write actions.
  - the object in one group of `API_SCOPE_GROUPS`. See the next section.
- MCP tools that call the endpoint: `scopes:` in `products/<product>/mcp/tools.yaml`.

## Choose a group

The OAuth consent screen and the scope pickers show objects in groups, from `API_SCOPE_GROUPS` in `frontend/src/lib/scopes.tsx`.
The groups make a long list readable, so a person can find a product quickly.

- A group is a product area that a person recognizes, such as "Session replay" or "Feature flags, experiments & surveys". It is not a code module or a team.
- Put the object in the existing group that a person would look in first.
- Add a new group only when it gets two or more objects. A group with one object makes the list longer, not easier to read.
- OAuth-hidden objects go in "Internal tools". The pickers do not show these objects, so a person never sees this group. Do not put a public object there, because it would show under the "Internal tools" label.

## Regenerate

Do not edit a generated file by hand.

- `hogli build:openapi`: regenerates `ScopeObjectEnumApi` from `GRANTABLE_API_SCOPE_OBJECTS`, through the `resource` fields of the access control serializers. The frontend `APIScopeObject` type is an alias of it, so a new object reaches the frontend here.
- `hogli build:projections`: regenerates the MCP OAuth scope list in `services/mcp/src/lib/oauth-scopes.generated.ts`.

## Read the scope list

- **Python:** import from `posthog.scopes`.
  - `API_SCOPE_OBJECTS`: every object, internal ones too.
  - `GRANTABLE_API_SCOPE_OBJECTS`: the objects a person can grant.
  - `ALL_SCOPES`: the grantable `object:action` strings.
  - `get_oauth_scopes_supported()`: what the OAuth server advertises.
- **Frontend type:** `APIScopeObject` from `~/types`.
- **Frontend list at runtime:** `Object.values(ScopeObjectEnumApi)`, from `products/access_control/frontend/generated/api.schemas`.
- **Frontend labels and groups:** `API_SCOPES`, `API_SCOPE_GROUPS` and `getScopeDescription` from `lib/scopes`.
- **MCP server:** `OAUTH_SCOPES_SUPPORTED` and `OAUTH_SCOPES_HIDDEN` from `services/mcp/src/lib/oauth-scopes.generated.ts`.

## Check your work

These tests catch most omissions:

- `frontend/src/lib/scopes.test.ts`:
  - "offers or explicitly omits every scope object" fails for an object with no picker row and no reason. Add one of the two.
  - "files every scope object in exactly one group" fails for an object in no group, or in two groups. Put the object in exactly one group of `API_SCOPE_GROUPS`.
- `posthog/test/test_scopes.py`: the internal, hidden and privileged sets, and the project secret API key lists.
- `services/mcp/tests/unit/tool-filtering.test.ts`: an MCP tool that needs a scope OAuth does not list.

No test catches a custom action without `required_scopes`, a read scope on a write action, or a wrong group or label.
Check these yourself.
Call each custom action with a personal API key that has only the new scope.
