import '~/styles'

import './buffer-polyfill'

import { Suspense, lazy } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import { retryBootImport } from 'lib/utils/retryImport'

import { RootErrorBoundary } from './RootErrorBoundary'
import { ChunkLoadErrorBoundary } from './scenes/ChunkLoadErrorBoundary'

type AppModules = [typeof import('scenes/App'), typeof import('scenes/bootApp')]

let appModulesPromise: Promise<AppModules> | undefined

function loadAppModules(): Promise<AppModules> {
    return (appModulesPromise ??= retryBootImport(() => import('lib/configureZod')).then(() =>
        Promise.all([retryBootImport(() => import('scenes/App')), retryBootImport(() => import('scenes/bootApp'))])
    ))
}

// Lazy-load App so the entry chunk stays minimal: the entire transitive dependency
// graph (kea, posthog-js, scene logic, UI components) is only fetched when it renders.
// lib/configureZod is imported on its own before the App chunk, because zod binds its
// jitless setting when it constructs each object schema and the App graph constructs
// some at module scope. bootApp() runs the remaining one-time boot side
// effects (posthog-js, kea) after the chunks load and before <App /> first renders.
// It lives in its own module so scenes/App keeps component-only exports and stays a
// React Fast Refresh boundary.
// boot() also starts the module imports while CSS loads; runtime initialization stays behind the render gate.
const App = lazy(() =>
    loadAppModules().then(([appModule, bootModule]) => {
        bootModule.bootApp()
        return { default: appModule.App }
    })
)

declare global {
    interface Window {
        __posthogAppRoot?: Root
    }
}

function getAppRoot(): Root | null {
    const rootElement = document.getElementById('root')
    if (!rootElement) {
        console.error('Attempted, but could not render PostHog app because <div id="root" /> is not found.')
        return null
    }
    // Vite 8 can serve this entry module twice after an HMR invalidation reaches it (the script
    // tag's bare URL plus a timestamped copy), and a second createRoot on an already-rooted
    // container crashes React. Reuse one root so a repeat execution re-renders instead.
    return (window.__posthogAppRoot ??= createRoot(rootElement))
}

function renderApp(): void {
    getAppRoot()?.render(
        <RootErrorBoundary>
            {/* Auto-reloads once on a chunk-load failure (stale deploy). Repeated or non-chunk
                errors bubble to RootErrorBoundary, which reports them and shows the failure UI. */}
            <ChunkLoadErrorBoundary>
                <Suspense
                    fallback={
                        <div className="Preloader" role="status" aria-label="Loading PostHog">
                            <div className="Preloader__inner" />
                        </div>
                    }
                >
                    <App />
                </Suspense>
            </ChunkLoadErrorBoundary>
        </RootErrorBoundary>
    )
}

function renderStylesheetFailure(): void {
    getAppRoot()?.render(
        <div className="Preloader" role="alert">
            <div>
                PostHog failed to load its styles.{' '}
                <button onClick={() => window.location.reload()}>Reload the page</button> to try again.
            </div>
        </div>
    )
}

// The boot stylesheet is attached by the loader script in the HTML, and this entry can finish
// before the sheet arrives. Rendering then paints the app unstyled until the sheet lands, so wait
// for it, but only briefly: a stylesheet that is merely slow must not hold the app back, and the
// loader keeps working on it in the background.
const CSS_READY_TIMEOUT_MS = 5000
function whenBootStylesheetReady(cssReady: Promise<boolean> | undefined): Promise<boolean | null> {
    if (!cssReady) {
        return Promise.resolve(null)
    }
    return Promise.race([
        cssReady,
        new Promise<null>((resolve) => setTimeout(() => resolve(null), CSS_READY_TIMEOUT_MS)),
    ])
}

function boot(): void {
    // Observe early failures until React mounts its boundaries, without replacing the rejected promise.
    void loadAppModules().catch(() => {})
    const cssReady = window.ESBUILD_CSS_READY
    // `false` means the loader ran out of stylesheet URLs, so every one of them failed. The app has
    // no styles of its own, so it would paint raw markup at natural size. Offer a reload instead.
    // A stalled attempt can hold the loader well past the render gate below, so this replaces the
    // app whenever the verdict arrives, not only when it beats the gate.
    void cssReady?.then((applied) => {
        if (!applied) {
            renderStylesheetFailure()
        }
    })
    void whenBootStylesheetReady(cssReady).then((applied) => {
        // `null` is the gate expiring on a sheet that is only slow. The loader keeps working on it
        // in the background, so render now rather than hold the app back.
        if (applied !== false) {
            renderApp()
        }
    })
}

// Render react only when DOM has loaded - javascript might be cached and loaded before the page is ready.
if (document.readyState !== 'loading') {
    boot()
} else {
    document.addEventListener('DOMContentLoaded', boot)
}
