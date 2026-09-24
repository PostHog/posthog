---
name: adding-api-scopes
description: 'Guidance for adding an API scope object to posthog/scopes.py and making it work for personal API keys, OAuth tokens and MCP clients. Use when adding a scope object, exposing a viewset or MCP tool to tokens, moving a viewset off scope_object = "INTERNAL", deciding if a scope is internal, OAuth-hidden or privileged, choosing a scope group, or when a scope test fails in scopes.test.ts, test_scopes.py or tool-filtering.test.ts. Trigger terms: new scope, APIScopeObject, scope_object, required_scopes, API_SCOPES, API_SCOPE_GROUPS, mcp scopes, OAuth scopes, personal API key scope.'
---

# Adding an API scope

A scope object such as `feature_flag` gives a token `feature_flag:read` and `feature_flag:write`.
`posthog/scopes.py` is the source of the object list.
Other lists are generated from it, and some are kept by hand.

## Decide if you need a new object

Most endpoints belong under an existing object.
Add a new object only for a product surface that a person wants to grant or refuse on its own.
Use a `snake_case` singular noun.

## Decide what kind of object it is

- **Public:** OAuth lists it, MCP can request it, and the key picker offers it. This is the default.
- **Internal:** only the server creates tokens with it. Use `INTERNAL_API_SCOPE_OBJECTS`.
- **OAuth-hidden:** a person can paste it into a personal API key, but OAuth clients do not see it. Use this for staff-only or unreleased surfaces. Use `OAUTH_HIDDEN_SCOPE_OBJECTS`.
- **Privileged:** only PostHog staff can give it to an OAuth app, through Django admin or a data migration. An app that registers itself cannot get it, and the CLI login and the key picker presets never include it. Use this for a scope that a partner app must not grant to itself, such as `llm_gateway`. Use `PRIVILEGED_SCOPES`, and set `unprivilegedExcluded: true` on the picker row.

Then decide two more things, separately from the kind:

- **Project secret API keys:** a project secret API key is a project credential with no user, for server-to-server calls. Allow the scope on it only when such a caller needs it. The allowed list is `PROJECT_SECRET_API_KEY_ALLOWED_API_SCOPE_ACTION`, in both `posthog/scopes.py` and `frontend/src/lib/scopes.tsx`. Read `/adding-project-secret-api-key-auth` first.
- **Access control:** if an organization must be able to restrict the resource per role or per object, add it to `ACCESS_CONTROL_RESOURCES` in `products/access_control/backend/facade/user_access_control.py`. Use the same name for the scope object and the resource.

## Choose a group

The OAuth consent screen and the scope pickers show objects in groups, from `API_SCOPE_GROUPS` in `posthog/scopes.py`.
The groups make a long list readable, so a person can find a product quickly.

- A group is a product area that a person recognizes, such as "Session replay" or "Feature flags, experiments & surveys". It is not a code module or a team.
- Put the object in the existing group that a person would look in first.
- Add a new group only when it gets two or more objects. A group with one object makes the list longer, not easier to read.
- Internal and OAuth-hidden objects go in "Internal tools".

If `API_SCOPE_GROUPS` does not exist yet, skip this step.

## Where the object must appear

- `posthog/scopes.py`: the `APIScopeObject` literal, the lists you chose above, and one group.
- The viewset: `scope_object`. Default actions map to read or write. A custom `@action` needs `required_scopes`, or tokens get a 403. Use `:read` for an action that only reads data, and `:write` for an action that changes data. `scope_object = "INTERNAL"` keeps an endpoint session-only.
- `frontend/src/lib/scopes.tsx`: a row in `API_SCOPES`, or a reason in `API_SCOPES_OMITTED_FROM_MODAL`. Labels are user-facing, so use sentence case (`/writing-user-facing-copy`). Disable `write` if the viewset has no write actions.
- MCP tools that call the endpoint: `scopes:` in `products/<product>/mcp/tools.yaml`.
- Generated files: run `hogli build:openapi`. Do not edit a `*.generated.ts` file by hand.

## Check your work

These tests catch most omissions:

- `frontend/src/lib/scopes.test.ts`: an object with no picker row and no reason, or an internal object in the picker.
- `posthog/test/test_scopes.py`: the project secret API key lists, and an object in no group or in two groups when groups exist.
- `services/mcp/tests/unit/tool-filtering.test.ts`: an MCP tool that needs a scope OAuth does not list.

No test catches a custom action without `required_scopes`, a read scope on a write action, or a wrong group or label.
Check these yourself.
Call each custom action with a personal API key that has only the new scope.
