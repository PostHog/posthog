---
name: working-in-the-toolbar
description: Guide for working in the PostHog toolbar (`frontend/src/toolbar/`). Use when adding or changing a toolbar feature, making an authenticated API request from the toolbar, adding a new API route or resource, or onboarding to how the toolbar is structured, authenticated, and mounted. Covers the blessed `toolbarApi` client, the `toolbarFetch` transport, auth/config state, logging, and telemetry.
---

# Working in the toolbar

The toolbar is the in-page overlay that PostHog injects into a customer's site (actions, heatmaps, web experiments, feature flags, surveys, product tours, and more). It lives in `frontend/src/toolbar/` and runs in a hostile environment: it shares the page with arbitrary customer code, talks to PostHog cross-origin, and authenticates with its own OAuth token rather than the app session.

Because of that, the toolbar does not use the main app's `lib/api`. It has its own fetching, auth, and observability stack. The rules below keep every feature consistent with it.

## The golden rule: fetch through `toolbarApi`

Every authenticated data request goes through `toolbarApi` (`frontend/src/toolbar/toolbarApi.ts`). Do not call `fetch`, `lib/api`, or `toolbarFetch` directly from feature code.

`toolbarApi` is a single, blessed client that folds every cross-cutting concern into one contract:

- It never throws. Network failures (offline, CORS, a customer page that replaced `window.fetch`) are caught and returned as a normal failure result, so no caller needs `try/catch` and no listener can leak an unhandled rejection.
- It always returns a discriminated union `ToolbarApiResult<T>` (`{ ok: true, data }` or `{ ok: false, error }`), so every call site branches on `result.ok` the same way.
- It centralizes observability. Every failure is logged via `toolbarLogger`; genuinely unexpected failures (network, 5xx, malformed JSON) are reported to error tracking, while expected ones (401/403 auth, 4xx validation) are logged but not reported.
- Toasts and re-authentication are opt-in via options, so background loaders stay quiet while user-initiated writes can surface a message.

### Calling it

Prefer the resource namespaces over the bare verbs. They own the route strings, so every `/api/projects/@current/...` path lives in exactly one place and call sites read as intent:

```ts
import { toolbarApi } from '~/toolbar/toolbarApi'

const result = await toolbarApi.actions.list({ context: 'load_actions' })
if (!result.ok) {
    return values.actions // soft-fail to existing state; the failure is already logged/reported
}
return result.data.results
```

For a user-initiated write, opt into a toast:

```ts
const result = await toolbarApi.surveys.update(id, payload, {
    context: 'save_survey',
    toastOnError: 'Could not save survey',
})
if (result.ok) {
    actions.resetForm()
}
```

### Options (`ToolbarApiOptions`)

- `context` (required): short snake_case string identifying the call site in logs, telemetry, and error tracking (e.g. `'load_actions'`).
- `toastOnError`: `false` (default, silent) for background loaders; a string fallback message for user-initiated writes; `true` to show the extracted error detail.
- `reauthenticateOnForbidden`: re-trigger the OAuth flow on 403 (project access lost or project switched). Default `false`.
- `captureOnError`: report unexpected failures to error tracking. Default `true`. Set `false` only when the caller deliberately re-raises so the exception is captured once.
- `urlConstruction`: `'use-as-provided'` for pagination URLs that come from a response body (pinned to the uiHost/apiHost origin). Default `'full'`.

## Extending the API: add a resource, not a raw route

When a feature needs a route that is not modeled yet, add a method to the relevant namespace (or a new namespace) in `toolbarApi.ts` rather than building a URL at the call site. Each method takes the resource-specific arguments plus `ToolbarApiOptions` and returns `ToolbarApiResult<T>`:

```ts
widgets: {
    list: (options: ToolbarApiOptions): Promise<ToolbarApiResult<{ results: Widget[] }>> =>
        apiGet(`${PROJECT}/widgets/`, options),
    update: (
        id: number | string,
        payload: Record<string, any>,
        options: ToolbarApiOptions
    ): Promise<ToolbarApiResult<Widget>> => apiPatch(`${PROJECT}/widgets/${id}/`, payload, options),
},
```

Conventions:

- Use the `PROJECT` (`/api/projects/@current`) and `ENVIRONMENT` (`/api/environments/@current`) path constants.
- Build query strings inside the method with `encodeParams` from `kea-router`, not at the call site.
- Bake the return type into the method when the type lives in a shared module (`~/types`, `~/toolbar/types`, `lib/api`). If the response type is defined inside a feature's own logic file, keep the method generic (`<T = unknown>`) and let the call site pass `<Type>`, so the API does not depend on feature code.
- The bare verbs (`toolbarApi.get/post/patch/delete`) are the low-level primitive the namespaces are built on. Reach for them only for a genuine one-off.

## The transport and auth layers (rarely touched)

You almost never need these directly, but it helps to know the layering:

- `toolbarFetch.ts`: the low-level authenticated transport. The single place that attaches the OAuth bearer, refreshes it on 401, clears the session on 403, and emits per-request telemetry. Returns a raw `Response`. It is kept free of `lemonToast` so it can be imported widely without dragging the toast layer into test setup. `toolbarUploadMedia` (multipart image upload) also lives here.
- `toolbarConfigLogic.ts`: config and auth state (access token, `uiHost`/`apiHost`, actions like `authenticate`, `tokenExpired`).
- `toolbarAuth.ts`: OAuth code exchange, token refresh (`withTokenRefresh`), and the reachability check.

Only two callers use `toolbarFetch` directly: `heatmapDataLogic` and `hedgehogModeLogic`. Both are dual-context shared logics in `lib/components` that interleave authenticated toolbar requests with unauthenticated `fetch` and need the raw `Response`. New toolbar features should not follow them, they should use `toolbarApi`.

### What deliberately does NOT use `toolbarApi`

Auth and bootstrap flows run before the toolbar is authenticated or before kea is mounted, so they own their own fetch behavior: the OAuth code exchange, token refresh, the reachability HEAD check, and the pre-mount feature-flag preload. Leave these alone.

## Other capabilities

- `toolbarLogger.ts`: structured logging (`toolbarLogger.info/warn/error(area, message, context)`). Used for anything you would otherwise `console.log`. `toolbarApi` already logs every request failure, so feature code rarely needs to log failures itself.
- `toolbarPosthogJS.ts`: the toolbar's own posthog-js instance for product telemetry (`toolbarPosthogJS.capture(...)`) and `captureToolbarException(...)`. Separate from the customer's posthog-js on the page.
- `toolbarConfigLogic`: read `apiURL`, `uiHost`, hosts, and feature flags here.
- Feature areas, one subdirectory each: `actions/`, `elements/`, `experiments/` (web experiments), `flags/`, `surveys/`, `product-tours/`, `field-notes/`, `web-vitals/`, `stats/` + heatmaps, `screenshot-upload/`, `hedgehog/`, `debug/`. Each is a kea logic plus its UI.

## When writing a toolbar feature

1. Put business logic in a kea logic, not a component (see [writing-kea-logics](../writing-kea-logics/SKILL.md)).
2. Fetch through `toolbarApi`, adding a resource method if the route is new.
3. Branch on `result.ok`; soft-fail loaders to existing state, toast user-initiated writes.
4. Do not add `try/catch` around `toolbarApi` calls, it never throws.
5. Reuse `toolbarLogger` and `toolbarPosthogJS` rather than `console` or a fresh posthog-js.
