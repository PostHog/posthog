# Frontend

The frontend is thin on purpose.
If the screen shows it, an API or MCP caller can get the same answer.

- **These are product decisions, and come from the API:** a name derived from data, a label, an outcome, a count, a grouping, whether something is stale.
- **A component renders.** It formats a value, and it shows placeholder copy where a value is missing. When unsure, put the decision on the server.
- **A component's props are the generated API types plus UI state, as separate props.** A frontend mapper exists only to join in state the server cannot know: selection, focus, loading.
- **A host binds a logic to components.** `useValues` and `useActions` go in a `*Host.tsx`, so components stay props-only and render in a story with no logic mounted.
- **A component's story renders at a narrow width.** Layout breaks show there first.
- **Purely visual toggle state may stay local in a component.** Anything reloadable, shared or worth a URL goes through a logic.
- **A loader that shows its own error throws, and only its toast is suppressed.** The failure still reaches error tracking. The list of suppressed loaders is in `frontend/src/initKea.ts`.
- **A read made outside a loader goes through `frontend/redesign/shared/readOrFailure.ts`.** It returns the value or the failure and reports the failure, so a failed read is never shown as empty.
- **State keyed by a string from data or a URL lives in a `Map`.** An id like `constructor` reads an inherited member on a plain object.
- **No version words in names.** No `v2`, `new`, `legacy` or `redesign` in symbols, file names, data-attrs, URLs or copy. Event names, data-attrs and URLs are API, and cannot be renamed later.
- **Clicks are counted by autocapture through readable `data-attr`s.** Own events cover only non-click actions and outcomes, documented in one tracking module per domain, like `frontend/redesign/trace/traceViewTracking.ts`.
