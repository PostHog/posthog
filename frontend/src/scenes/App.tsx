import { Tooltip as BaseTooltip } from '@base-ui/react/tooltip'
import { BindLogic, useMountedLogic, useValues } from 'kea'
import posthog from 'posthog-js'
import React, { Suspense, useEffect } from 'react'

import { PostHogProvider } from '@posthog/react'

import { MOCK_NODE_PROCESS } from 'lib/constants'
import { useCancelAnimationsOnUnmount } from 'lib/hooks/useCancelAnimationsOnUnmount'
import { useThemedHtml } from 'lib/hooks/useThemedHtml'
import { ToastCloseButton } from 'lib/lemon-ui/LemonToast/LemonToast'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { autofillReleaseLogic } from 'lib/memory/autofillReleaseLogic'
import { OAuthCallback } from 'lib/oauth/OAuthCallback'
import { oauthLogic } from 'lib/oauth/oauthLogic'
import { retryImport } from 'lib/utils/retryImport'
import { appLogic } from 'scenes/appLogic'
import { appScenes } from 'scenes/appScenes'
import { sceneLogic } from 'scenes/sceneLogic'
import { userLogic } from 'scenes/userLogic'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { initKea } from '../initKea'
import { loadPostHogJS } from '../loadPostHogJS'
import { ChunkLoadErrorBoundary } from './ChunkLoadErrorBoundary'

const AuthenticatedShell = React.lazy(() => retryImport(() => import('./AuthenticatedShell')))

window.process = MOCK_NODE_PROCESS

// Kea must initialize synchronously before any component mounts
initKea()
// Deferred to a microtask so React starts rendering before posthog-js issues network calls
queueMicrotask(loadPostHogJS)

const idle =
    typeof window !== 'undefined' && typeof window.requestIdleCallback === 'function'
        ? window.requestIdleCallback.bind(window)
        : (cb: () => void) => setTimeout(cb, 200)

idle(() => {
    void import('./session-recordings/player/snapshot-processing/DecompressionWorkerManager')
        .then(({ preWarmDecompression }) => preWarmDecompression())
        .catch(() => {})

    // On Chrome + Windows, the country flag emojis don't render correctly. This polyfill fixes that.
    // NOTE: The first argument sets the polyfill's font family name, which our CSS references —
    // keep the two in sync. Detection is canvas-based and can throw on some browser states
    // (e.g. Safari/macOS); it's purely cosmetic, so swallow any failure.
    void import('country-flag-emoji-polyfill')
        .then(({ polyfillCountryFlagEmojis }) => polyfillCountryFlagEmojis('Emoji Flags Polyfill'))
        .catch(() => {})
})

/**
 * Wraps each rendered scene so that when the scene unmounts (on tab change
 * or scene swap), every running CSS / Web Animation under it is cancelled
 * before the DOM detaches. This severs the `DocumentTimeline -> animation
 * -> element` chain that otherwise pins detached scene trees in memory
 * across SPA navigation, and lets the browser GC the trees normally.
 *
 * `display: contents` keeps the wrapper transparent to layout.
 */
function SceneAnimationRoot({ children }: { children: React.ReactNode }): JSX.Element {
    const ref = useCancelAnimationsOnUnmount<HTMLDivElement>()
    return (
        // `className="contents"` is load-bearing: the wrapper must take a DOM
        // node so the ref has something to attach to (we need an element to
        // call `getAnimations({ subtree: true })` on), but it must also be
        // transparent to layout. `display: contents` removes it from the box
        // tree so children render as if there's no wrapper.
        <div ref={ref} className="contents">
            {children}
        </div>
    )
}

/** Lazy-loaded Kea devtools panel, only rendered in dev mode with dev tools open */
function KeaDevtoolsLoader(): JSX.Element | null {
    const [DevTools, setDevTools] = React.useState<React.ComponentType | null>(null)
    React.useEffect(() => {
        import('lib/KeaDevTools').then((mod) => setDevTools(() => mod.KeaDevtools)).catch(() => {})
    }, [])
    return DevTools ? <DevTools /> : null
}

export function App(): JSX.Element | null {
    const { showApp, showingDelayedSpinner, showingDevTools } = useValues(appLogic)

    useMountedLogic(sceneLogic({ scenes: appScenes }))
    useMountedLogic(autofillReleaseLogic)
    // Unconditional so /oauth/callback's urlToAction is registered before routing. Inert in prod
    // (OAuth UI gated on preflight.is_debug); no timers/listeners, so cheap to always mount.
    useMountedLogic(oauthLogic)

    // Mount the support-hash router (handles #panel=support) on every page, lazily so it stays out
    // of App's import graph — a static import drags supportLogic/sceneLogic/organizationLogic into
    // root init and triggers a circular-import TDZ. Its urlToAction fires on the current URL on mount.
    useEffect(() => {
        let unmount: (() => void) | undefined
        void import('lib/components/Support/supportRouterLogic').then(({ supportRouterLogic }) => {
            unmount = supportRouterLogic.mount()
        })
        return () => unmount?.()
    }, [])

    useThemedHtml()

    // A cloud OAuth redirect lands at /oauth/callback on the local origin. Render the exchange
    // screen here (oauthLogic's urlToAction performs the token exchange), before normal routing.
    if (window.location.pathname === '/oauth/callback') {
        return (
            <ErrorBoundary>
                <PostHogProvider client={posthog}>
                    <OAuthCallback />
                </PostHogProvider>
            </ErrorBoundary>
        )
    }

    const sceneContent = (
        <ErrorBoundary>
            <PostHogProvider client={posthog}>
                <BaseTooltip.Provider delay={500} closeDelay={0} timeout={400}>
                    {showApp ? (
                        <>
                            <AppScene />
                            {showingDevTools ? <KeaDevtoolsLoader /> : null}
                        </>
                    ) : (
                        <SpinnerOverlay sceneLevel visible={showingDelayedSpinner} />
                    )}
                </BaseTooltip.Provider>
            </PostHogProvider>
        </ErrorBoundary>
    )

    return sceneContent
}

function AppScene(): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { activeSceneId, activeExportedScene, activeSceneComponentParams, activeSceneLogicProps, sceneConfig } =
        useValues(sceneLogic)
    const { showingDelayedSpinner } = useValues(appLogic)
    const { isDarkModeOn } = useValues(themeLogic)

    // Once we know the user is authenticated, kick off an idle prefetch of the
    // AuthenticatedShell chunk so the Suspense fallback rarely actually fires
    // when the shell mounts. No-op on prefetch failure — Suspense still works.
    useEffect(() => {
        if (!user) {
            return
        }
        const idle =
            typeof window.requestIdleCallback === 'function'
                ? window.requestIdleCallback.bind(window)
                : (cb: () => void) => setTimeout(cb, 200)
        idle(() => {
            void import('./AuthenticatedShell').catch(() => {
                /* prefetch is best-effort; the real Suspense load will surface failures */
            })
        })
    }, [user])

    const [ToastLazy, setToastLazy] = React.useState<typeof import('react-toastify') | null>(null)
    useEffect(() => {
        if (!user) {
            import('react-toastify').then((mod) => setToastLazy(mod)).catch(() => {})
        }
    }, [user])

    const unauthToastContainer = ToastLazy ? (
        <ToastLazy.ToastContainer
            autoClose={6000}
            transition={ToastLazy.Slide}
            closeButton={<ToastCloseButton />}
            position="bottom-right"
            theme={isDarkModeOn ? 'dark' : 'light'}
        />
    ) : null

    let sceneElement: JSX.Element
    if (activeExportedScene?.component) {
        const { component: SceneComponent } = activeExportedScene
        sceneElement = (
            <SceneAnimationRoot key={`scene-${activeSceneId}`}>
                <SceneComponent user={user} {...activeSceneComponentParams} />
            </SceneAnimationRoot>
        )
    } else {
        sceneElement = <SpinnerOverlay sceneLevel visible={showingDelayedSpinner} />
    }

    const sceneContent = activeExportedScene?.logic ? (
        <BindLogic key={`bind-${activeSceneId}`} logic={activeExportedScene.logic} props={activeSceneLogicProps}>
            {sceneElement}
        </BindLogic>
    ) : (
        sceneElement
    )

    const wrappedSceneElement = (
        <ErrorBoundary key={`error-${activeSceneId}`} exceptionProps={{ feature: activeSceneId }}>
            {/* Keep chunk-load failures out of the scene error reporter so stale assets reload once instead. */}
            <ChunkLoadErrorBoundary>{sceneContent}</ChunkLoadErrorBoundary>
        </ErrorBoundary>
    )

    if (!user) {
        return sceneConfig?.onlyUnauthenticated || sceneConfig?.allowUnauthenticated ? (
            <>
                {wrappedSceneElement}
                {unauthToastContainer}
            </>
        ) : null
    }

    return (
        <ChunkLoadErrorBoundary>
            <Suspense
                fallback={
                    // SpinnerOverlay is already imported here — no new lazy deps vs skeleton.
                    <div className="relative h-screen">
                        <SpinnerOverlay sceneLevel />
                    </div>
                }
            >
                <AuthenticatedShell>{wrappedSceneElement}</AuthenticatedShell>
            </Suspense>
        </ChunkLoadErrorBoundary>
    )
}
