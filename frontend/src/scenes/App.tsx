import { BindLogic, useMountedLogic, useValues } from 'kea'
import React, { Suspense, useEffect } from 'react'
import { Slide, ToastContainer } from 'react-toastify'

import { MOCK_NODE_PROCESS } from 'lib/constants'
import { useCancelAnimationsOnUnmount } from 'lib/hooks/useCancelAnimationsOnUnmount'
import { useThemedHtml } from 'lib/hooks/useThemedHtml'
import { KeaDevtools } from 'lib/KeaDevTools'
import { ToastCloseButton } from 'lib/lemon-ui/LemonToast/LemonToast'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
import { appLogic } from 'scenes/appLogic'
import { appScenes } from 'scenes/appScenes'
import { sceneLogic } from 'scenes/sceneLogic'
import { userLogic } from 'scenes/userLogic'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { ChunkLoadErrorBoundary } from './ChunkLoadErrorBoundary'

const AuthenticatedShell = React.lazy(() => import('./AuthenticatedShell'))

window.process = MOCK_NODE_PROCESS

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

export function App(): JSX.Element | null {
    const { showApp, showingDelayedSpinner, showingDevTools } = useValues(appLogic)

    useMountedLogic(sceneLogic({ scenes: appScenes }))

    useThemedHtml()

    if (showApp) {
        return (
            <>
                <AppScene />
                {showingDevTools ? <KeaDevtools /> : null}
            </>
        )
    }

    return <SpinnerOverlay sceneLevel visible={showingDelayedSpinner} />
}

function AppScene(): JSX.Element | null {
    const { user } = useValues(userLogic)
    const {
        activeSceneId,
        activeExportedScene,
        activeSceneComponentParamsWithTabId,
        activeSceneLogicPropsWithTabId,
        sceneConfig,
    } = useValues(sceneLogic)
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

    const unauthToastContainer = (
        <ToastContainer
            autoClose={6000}
            transition={Slide}
            closeButton={<ToastCloseButton />}
            position="bottom-right"
            theme={isDarkModeOn ? 'dark' : 'light'}
        />
    )

    let sceneElement: JSX.Element
    if (activeExportedScene?.component) {
        const { component: SceneComponent } = activeExportedScene
        sceneElement = (
            <SceneAnimationRoot key={`scene-${activeSceneId}-${activeSceneLogicPropsWithTabId.tabId}`}>
                <SceneComponent user={user} {...activeSceneComponentParamsWithTabId} />
            </SceneAnimationRoot>
        )
    } else {
        sceneElement = <SpinnerOverlay sceneLevel visible={showingDelayedSpinner} />
    }

    const wrappedSceneElement = (
        <ErrorBoundary
            key={`error-${activeSceneLogicPropsWithTabId.tabId}`}
            exceptionProps={{ feature: activeSceneId }}
        >
            {activeExportedScene?.logic ? (
                <BindLogic
                    key={`bind-${activeSceneLogicPropsWithTabId.tabId}`}
                    logic={activeExportedScene.logic}
                    props={activeSceneLogicPropsWithTabId}
                >
                    {sceneElement}
                </BindLogic>
            ) : (
                sceneElement
            )}
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
                    <WrappingLoadingSkeleton fullWidth>
                        <span className="block w-full h-screen" />
                    </WrappingLoadingSkeleton>
                }
            >
                <AuthenticatedShell>{wrappedSceneElement}</AuthenticatedShell>
            </Suspense>
        </ChunkLoadErrorBoundary>
    )
}
