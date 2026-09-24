---
name: adding-api-scopes
description: 'How to add, classify, or rename an API scope object in posthog/scopes.py and wire it through every place that reads it: viewset scope declarations, the personal API key picker, the OAuth and MCP scope lists, project secret API keys, access control, and MCP tools. Use when adding a scope object, exposing a viewset or MCP tool to personal API keys, OAuth tokens or MCP clients, moving a viewset off scope_object = "INTERNAL", making a scope internal, OAuth-hidden or privileged, or when a scope test fails in scopes.test.ts, test_scopes.py or tool-filtering.test.ts. Trigger terms: new scope, APIScopeObject, scope_object, required_scopes, API_SCOPES, API_SCOPES_OMITTED_FROM_MODAL, mcp scopes, OAuth scopes, personal API key scope.'
---

# Adding an API scope

A scope object such as `feature_flag` gives a token `feature_flag:read` and `feature_flag:write`.
`posthog/scopes.py` is the source of the object list, but several other places read it.
Some of them are generated, some are hand-kept, and a few choices no check can make for you.
This skill covers all of them, in the order you meet them.

## First, decide if you need a new object

Most new endpoints belong under an existing object.
An endpoint that reads feature flags uses `feature_flag`, even when it lives in another product.
Add a new object only for a new product surface that a person would want to grant or refuse on its own.

Name it in `snake_case`, as a singular noun for the thing it guards (`review_hog`, `data_deletion`).
If the object is also an access-control resource, use the same name for both.
`obj:write` must stay within 100 characters, because `OAuthApplication.scopes` and `PersonalAPIKey.scopes` store each scope in a `CharField(max_length=100)`.

## Classify the object

Decide each of these before you write code.
Each answer puts the object in one more list.

| Question                                                                                                                      | If yes                  | Where                                                                                                                                                              |
| ----------------------------------------------------------------------------------------------------------------------------- | ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Can only the server mint it, never a person?                                                                                  | Internal                | `INTERNAL_API_SCOPE_OBJECTS` in `posthog/scopes.py`                                                                                                                |
| Can a person paste it into a personal API key, but OAuth clients and MCP must not discover it? (staff-only or not yet public) | OAuth-hidden            | `OAUTH_HIDDEN_SCOPE_OBJECTS` in `posthog/scopes.py`                                                                                                                |
| Must every unprivileged preset and OAuth default exclude it?                                                                  | Privileged              | `PRIVILEGED_SCOPES` in `posthog/scopes.py`, and `unprivilegedExcluded: true` on its picker row                                                                     |
| Do project secret API keys need it?                                                                                           | Allowed on PSAKs        | `PROJECT_SECRET_API_KEY_ALLOWED_API_SCOPE_ACTION` in both `posthog/scopes.py` and `frontend/src/lib/scopes.tsx`. Read `/adding-project-secret-api-key-auth` first. |
| Can an organization restrict it per role or per object?                                                                       | Access-control resource | `ACCESS_CONTROL_RESOURCES` in `products/access_control/backend/facade/user_access_control.py`. See below.                                                          |

Everything else is a public object: OAuth advertises it, MCP can request it, and the key picker offers it.

## Steps

1. **Backend list.** Add the object to the `APIScopeObject` literal in `posthog/scopes.py`, and to the sets you chose above.
   If `API_SCOPE_GROUPS` exists in that file, put the object in exactly one group.
   Internal and OAuth-hidden objects go in the "Internal tools" group.
2. **Viewset.** Set `scope_object = "<object>"`.
   `list` and `retrieve` need `read`.
   `create`, `update`, `partial_update`, `patch` and `destroy` need `write`.
   A custom `@action` is in neither list, so tokens get "This action does not support personal API key access" until you declare it.
   Put `required_scopes=["<object>:read"]` on the `@action`, or list the action names in `scope_object_read_actions` or `scope_object_write_actions` on the viewset.
   Those two lists replace the defaults, so name every action they must cover.
   `scope_object = "INTERNAL"` keeps the endpoint session-only.
   Use `dangerously_get_required_scopes` only when the required scope depends on the request itself.
3. **Picker.** Add a row to `API_SCOPES` in `frontend/src/lib/scopes.tsx`, with `objectName` and `objectPlural` in sentence case.
   Add `disabledActions: ['write']` when the viewset has no write actions.
   An internal, OAuth-hidden or retired object gets an entry with a reason in `API_SCOPES_OMITTED_FROM_MODAL` instead.
   Invoke `/writing-user-facing-copy` for the labels.
4. **Access control, only for access-control resources.** Add the object to `ACCESS_CONTROL_RESOURCES`.
   Add a case to `resource_to_display_name` when the plural of the name reads badly, and to `default_access_level` when new resources must start locked.
   Read the `access-control` agent definition for the viewset and serializer mixins.
   Its paths into `posthog/scopes.py` for `ACCESS_CONTROL_RESOURCES` are out of date.
5. **MCP tools.** Name the scope under `scopes:` on every tool in `products/<product>/mcp/tools.yaml` that calls the endpoint.
   Invoke `/implementing-mcp-tools` for the rest of the tool.
6. **Regenerate.** Run `hogli build:openapi`, which needs the dev stack.
   It rewrites these files from `posthog/scopes.py`, and you commit them:
   - `frontend/src/lib/scopeObjects.generated.ts`: the object list and the internal and OAuth-hidden sets.
   - `services/mcp/src/lib/oauth-scopes.generated.ts`: the scopes OAuth advertises to MCP clients.
   - `frontend/src/lib/agentScopes.generated.ts`: the scopes of the CLI agent login, from the MCP tools.
   - `frontend/src/lib/scopeGroups.generated.ts`, when `API_SCOPE_GROUPS` exists.

   Without the stack, `hogli build:openapi-scope-objects` and `hogli build:openapi-mcp-scopes` run alone.
   Kea typegen can also rewrite `APIScopeObject` unions in logic files such as `accessControlLogic.ts`. Commit those changes too.

Never edit a generated file by hand. CI's OpenAPI job regenerates it and fails on drift.

## What CI catches, and what it does not

| Mistake                                                    | Caught by                                                     |
| ---------------------------------------------------------- | ------------------------------------------------------------- |
| A backend object with no picker row and no omission reason | `frontend/src/lib/scopes.test.ts`                             |
| An internal or OAuth-hidden object that the picker offers  | `frontend/src/lib/scopes.test.ts`                             |
| A group missing an object, or naming an unknown one        | `posthog/test/test_scopes.py`, when `API_SCOPE_GROUPS` exists |
| The two PSAK lists disagree                                | `posthog/test/test_scopes.py`                                 |
| A scope longer than 100 characters                         | `posthog/test/test_scopes.py`                                 |
| An MCP tool needs a scope OAuth does not advertise         | `services/mcp/tests/unit/tool-filtering.test.ts`              |
| A typo in `scope_object`                                   | mypy, because the field takes the `APIScopeObject` literal    |
| A custom action without `required_scopes`                  | nothing, tokens get a 403 at runtime                          |
| The wrong classification, group, or label                  | nothing, a reviewer must check it                             |

Test a custom action with a personal API key that carries only the new scope, and assert both the allowed and the refused case.

## Renaming or removing an object

Personal API keys, OAuth grants and application ceilings store scope strings, so a rename breaks every existing grant.
Keep the old object until no grant uses it.
While it waits, give it a "Pending removal" entry in `API_SCOPES_OMITTED_FROM_MODAL`, like `batch_import`, so nobody new can grant it.
Removing an object needs the same care as removing a field.
Search for the string in fixtures, MCP tool definitions and docs before you delete it.
