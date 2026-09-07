# Frontend boot order

`frontend/src/index.tsx` starts loading the app modules once the document is ready.
Module loading runs while the boot stylesheet loads.
The modules remain separate from the entry bundle.

## Loading and initialization

1. Load and run `configureZod` before importing App or `bootApp`.
   Zod binds its configuration when the app modules construct schemas.
2. Load App and the `bootApp` module together.
   Reuse the same loading promise when React renders the lazy App component.
3. Wait for the boot stylesheet before rendering React.
   Keep the existing five-second timeout so a stalled stylesheet cannot block startup indefinitely.
4. Call `bootApp()` from the lazy component before rendering App.
   Module preloading must not start the PostHog SDK or Kea runtime.

Keep preloading after DOM readiness.
Dynamic imports evaluate module-level code, so moving them earlier requires checking those modules for access to the document.

## Failure handling

Observe an early preload rejection while CSS is pending, but retain the original rejected promise.
React must receive that rejection after its error boundaries mount.
Do not replace the failure with a successful preload result or report it twice.

## Verification

`frontend/src/index.test.tsx` covers parallel loading, Zod ordering, stylesheet success and failure, the timeout, and early import failures.
For browser checks, delay the stylesheet and compare styled content readiness as well as first paint.
Do not remove the stylesheet gate just to paint an unstyled page sooner.
