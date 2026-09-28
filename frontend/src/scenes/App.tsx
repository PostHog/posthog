import { Tooltip as BaseTooltip } from '@base-ui/react/tooltip'
import { useMountedLogic, useValues } from 'kea'
import posthog from 'posthog-js'
import React, { Suspense, useEffect } from 'react'
import { Slide, ToastContainer } from 'react-toastify'

import { PostHogProvider } from '@posthog/react'

import { productSetupPreloadLogic } from 'lib/components/ProductEmptyState/productSetupPreloadLogic'
import { MOCK_NODE_PROCESS } from 'lib/constants'
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

import { AppLoadError } from '~/layout/AppLoadError'
import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { ActiveScene } from './ActiveScene'
import { AuthenticatedShellFallback } from './AuthenticatedShellFallback'
import { ChunkLoadErrorBoundary } from './ChunkLoadErrorBoundary'

const AuthenticatedShell = React.lazy(() => retryImport(() => import('./AuthenticatedShell')))

window.process = MOCK_NODE_PROCESS

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

    // Resolves product setup statuses on idle, so gated scenes open without a spinner.
    useMountedLogic(productSetupPreloadLogic)

    // Unconditional so /oauth/callback's urlToAction is registered before routing. Inert in prod
    // (OAuth UI gated on preflight.is_debug); no timers/listeners, so cheap to always mount.
    useMountedLogic(oauthLogic)

    // Mount the support-hash router (handles #panel=support) on every page, lazily so it stays out
    // of App's import graph — a static import drags supportLogic/sceneLogic/organizationLogic into
    // root init and triggers a circular-import TDZ. Its urlToAction fires on the current URL on mount.
    useEffect(() => {
        let unmount: (() => void) | undefined
        void retryImport(() => import('lib/components/Support/supportRouterLogic')).then(({ supportRouterLogic }) => {
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
    const { sceneConfig } = useValues(sceneLogic)
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
            void Promise.all([
                import('./AuthenticatedShell'),
                import('lib/components/ProductEmptyState/ProductEmptyStateGate'),
            ]).catch(() => {
                /* prefetch is best-effort; the real Suspense load will surface failures */
            })
        })
    }, [user])

    const unauthToastContainer = (
        <ToastContainer
            autoClose={6000}
            transition={Slide}
            closeButton={<ToastCloseButton />}
            position="bottom-right"
            theme={isDarkModeOn ? 'dark' : 'light'}
        />
    )

    const wrappedSceneElement = <ActiveScene />

    if (!user) {
        return sceneConfig?.onlyUnauthenticated || sceneConfig?.allowUnauthenticated ? (
            <>
                {wrappedSceneElement}
                {unauthToastContainer}
            </>
        ) : null
    }

    return (
        <ChunkLoadErrorBoundary fallback={(error) => <AppLoadError error={error} />}>
            <Suspense fallback={<AuthenticatedShellFallback showSpinner={showingDelayedSpinner} />}>
                <AuthenticatedShell>{wrappedSceneElement}</AuthenticatedShell>
            </Suspense>
        </ChunkLoadErrorBoundary>
    )
}
