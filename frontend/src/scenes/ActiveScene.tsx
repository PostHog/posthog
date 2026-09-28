import { BindLogic, useValues } from 'kea'
import { type ReactNode, Suspense } from 'react'

import { useCancelAnimationsOnUnmount } from 'lib/hooks/useCancelAnimationsOnUnmount'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { appLogic } from 'scenes/appLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { userLogic } from 'scenes/userLogic'

import { ErrorBoundary } from '~/layout/ErrorBoundary'

import { ChunkLoadErrorBoundary } from './ChunkLoadErrorBoundary'

// Lazy for the same reason as AuthenticatedShell: the gate renders SceneTitleSection, whose static
// graph is most of the authenticated navigation. Importing it here put ~3.7 MiB of logged-in UI on
// the boot path that /login and /signup preload. Its dependencies already ship with the shell, so
// for logged-in users this chunk is small and is prefetched alongside the shell below.
const ProductEmptyStateGate = lazyWithRetry(() =>
    import('lib/components/ProductEmptyState/ProductEmptyStateGate').then((m) => ({
        default: m.ProductEmptyStateGate,
    }))
)

/**
 * Wraps each rendered scene so that when the scene unmounts (on tab change
 * or scene swap), every running CSS / Web Animation under it is cancelled
 * before the DOM detaches. This severs the `DocumentTimeline -> animation
 * -> element` chain that otherwise pins detached scene trees in memory
 * across SPA navigation, and lets the browser GC the trees normally.
 *
 * `display: contents` keeps the wrapper transparent to layout.
 */
function SceneAnimationRoot({ children }: { children: ReactNode }): JSX.Element {
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

/** The scene the router resolved, with its logic, empty-state gate and error boundaries, and no app chrome. */
export function ActiveScene(): JSX.Element {
    const { user } = useValues(userLogic)
    const { activeSceneId, activeExportedScene, activeSceneComponentParams, activeSceneLogicProps } =
        useValues(sceneLogic)
    const { showingDelayedSpinner } = useValues(appLogic)

    let sceneElement: JSX.Element
    if (activeExportedScene?.component) {
        const { component: SceneComponent, emptyState } = activeExportedScene
        const sceneNode = <SceneComponent user={user} {...activeSceneComponentParams} />

        // Scenes that declare an empty state are gated behind the product's
        // setup screen until the product has data (or the user skips).
        const resolvedNode = emptyState ? (
            <Suspense fallback={<SpinnerOverlay sceneLevel visible={showingDelayedSpinner} />}>
                <ProductEmptyStateGate emptyState={emptyState} params={activeSceneComponentParams}>
                    {sceneNode}
                </ProductEmptyStateGate>
            </Suspense>
        ) : (
            sceneNode
        )

        sceneElement = <SceneAnimationRoot key={`scene-${activeSceneId}`}>{resolvedNode}</SceneAnimationRoot>
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

    return wrappedSceneElement
}
