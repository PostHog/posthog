# Endpoints and PostHog AI

The Endpoints list and endpoint detail page attach context to the existing PostHog AI side panel.
This integration uses the sandbox runtime and the existing `PHAI_SCENE_AUTO_OPEN` rollout gate.
It does not automatically open the panel.

On an endpoint, **Ask AI** offers prompts for the selected tab: query explanation, performance and
materialization, versions, client examples, and failure investigation. Selecting a prompt opens the
panel with editable text; the user sends it when ready.

Context identifies the endpoint by name, the selected version, the active tab, and whether there
are unsaved changes. It does not include API keys, playground payloads, execution results, or full
saved endpoint definitions. The agent fetches saved definitions through endpoint tools. The SQL
editor continues to attach its own live query context and display SQL suggestions as accept/reject
diffs. Unsaved configuration is indicated but its contents are not attached.

SQL suggestions do not save an endpoint. Saving a query creates the new latest version immediately,
which changes the behavior of unpinned callers. There is no persisted draft or separate publish step.
The agent instructions distinguish that operation from changes to a specific version's settings.

An `endpoint-update` completion from the foreground run refreshes the matching endpoint, preserving
the selected tab and version. The subscription excludes replay and checks the endpoint name against
the open page. Unsaved configuration, SQL edits or suggestions, playground
payloads, and an in-progress save defer the refresh. A banner offers an explicit reload with a
discard confirmation. The endpoint list refreshes after create, update, and delete completions.

The integration uses `useSceneAgentPanel` and `useToolStreamListener`. Refreshes use a stream listener
so multiple updates in one turn continue refreshing after the editor remounts.
See [PostHog AI integration](../../products/posthog_ai/README.md) for the shared frontend contract.
