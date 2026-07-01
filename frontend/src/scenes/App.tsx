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
// PostHog self-capture initialization deferred to microtask — posthog-js singleton is
// already importable, and init() just configures it. Deferring lets the App chunk
// evaluate faster and React start rendering before posthog-js network calls complete.
queueMicrotask(loadPostHogJS)

// Deferred idle work — pre-warm decompression workers, polyfill emoji flags, etc.
const idle =
    typeof window !== 'undefined' && typeof window.requestIdleCallback === 'function'
        ? window.requestIdleCallback.bind(window)
        : (cb: () => void) => setTimeout(cb, 200)

idle(() => {
    void import('./session-recordings/player/snapshot-processing/DecompressionWorkerManager')
        .then(({ preWarmDecompression }) => preWarmDecompression())
        .catch(() => {})

    // On Chrome + Windows, the country flag emojis don't render correctly. This polyfill fixes that.
    try {
        void import('country-flag-emoji-polyfill').then(({ polyfillCountryFlagEmojis }) =>
            polyfillCountryFlagEmojis('Emoji Flags Polyfill')
        )
    } catch {
        /* best-effort polyfill */
    }
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
        <div ref={ref} className="contents">
            {children}
        </div>
    )
}

/** Lazy-loaded Kea devtools panel — only rendered in dev mode with dev tools open */
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
    useMountedLogic(oauthLogic)

    useEffect(() => {
        let unmount: (() => void) | undefined
        void import('lib/components/Support/supportRouterLogic').then(({ supportRouterLogic }) => {
            unmount = supportRouterLogic.mount()
        })
        return () => unmount?.()
    }, [])

    useThemedHtml()

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

    useEffect(() => {
        if (!user) {
            return
        }
        const idle =
            typeof window.requestIdleCallback === 'function'
                ? window.requestIdleCallback.bind(window)
                : (cb: () => void) => setTimeout(cb, 200)
        idle(() => {
            void import('./AuthenticatedShell').catch(() => {})
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
