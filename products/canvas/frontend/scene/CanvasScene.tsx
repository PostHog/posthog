import { BindLogic, useActions, useValues } from 'kea'

import { IconWarning } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Skeleton,
} from '@posthog/quill'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { CanvasBrowsedCanvas } from '../history/CanvasBrowsedCanvas'
import { CanvasHistoryConfirmDialog } from '../history/CanvasHistoryConfirmDialog'
import { canvasHistoryLogic } from '../history/canvasHistoryLogic'
import { CanvasSidePanel } from '../sidePanel/CanvasSidePanel'
import { canvasCommentsLogic } from '../sidePanel/comments/canvasCommentsLogic'
import { CanvasSelectionCommentAction } from '../sidePanel/comments/CanvasSelectionCommentAction'
import { CanvasEmptyBody } from './CanvasEmptyBody'
import { CanvasGeneratingState } from './CanvasGeneratingState'
import { CanvasRenderer } from './CanvasRenderer'
import { CanvasSceneHeader } from './CanvasSceneHeader'
import { CanvasSceneLogicProps, canvasSceneLogic } from './canvasSceneLogic'

export const scene: SceneExport<CanvasSceneLogicProps> = {
    component: CanvasScene,
    logic: canvasSceneLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

function CanvasBody(): JSX.Element {
    const { bodyState, viewLoading, liveRenderSource } = useValues(canvasSceneLogic)
    const { loadView } = useActions(canvasSceneLogic)
    const { browseVersionId } = useValues(canvasHistoryLogic)

    if (browseVersionId && bodyState !== 'missing' && bodyState !== 'error') {
        return <CanvasBrowsedCanvas />
    }
    switch (bodyState) {
        case 'loading':
            return (
                <div className="flex h-full flex-col gap-3 py-2">
                    <Skeleton className="h-4 w-1/3" />
                    <Skeleton className="h-full w-full" />
                </div>
            )
        case 'error':
            return (
                <Empty className="h-full">
                    <EmptyHeader>
                        <EmptyMedia variant="icon">
                            <IconWarning />
                        </EmptyMedia>
                        <EmptyTitle>This canvas didn't load</EmptyTitle>
                        <EmptyDescription>Check your connection and try again.</EmptyDescription>
                    </EmptyHeader>
                    <EmptyContent>
                        <Button
                            variant="outline"
                            loading={viewLoading}
                            onClick={() => loadView()}
                            data-attr="canvas-load-retry"
                        >
                            Try again
                        </Button>
                    </EmptyContent>
                </Empty>
            )
        case 'empty':
            return <CanvasEmptyBody />
        case 'generation-ended':
            return (
                <CanvasEmptyBody notice="The last run finished without a canvas to show. Describe it again to start a new run." />
            )
        case 'generating':
            return <CanvasGeneratingState />
        case 'draft-unavailable':
            return (
                <Empty className="h-full">
                    <EmptyHeader>
                        <EmptyMedia variant="icon">
                            <IconWarning />
                        </EmptyMedia>
                        <EmptyTitle>This draft can't be shown here</EmptyTitle>
                        <EmptyDescription>
                            Drafts render from a separate canvas origin, and this PostHog instance doesn't have one set
                            up. The canvas shows here once it's built, or you can open it in PostHog Desktop.
                        </EmptyDescription>
                    </EmptyHeader>
                </Empty>
            )
        case 'built':
        case 'draft':
            return <CanvasRenderer source={liveRenderSource} />
        case 'missing':
            return <NotFound object="canvas" />
    }
}

export function CanvasScene({ id }: CanvasSceneLogicProps): JSX.Element {
    const enabled = useFeatureFlag('TODAY_RAIL_NAV')
    const { viewMissing, sidePanelOpen } = useValues(canvasSceneLogic({ id }))

    if (!enabled || viewMissing) {
        return <NotFound object="canvas" />
    }
    return (
        <BindLogic logic={canvasSceneLogic} props={{ id }}>
            <BindLogic logic={canvasHistoryLogic} props={{ id }}>
                <BindLogic logic={canvasCommentsLogic} props={{ id }}>
                    <SceneContent className="h-full min-h-0 gap-y-2">
                        <CanvasSceneHeader />
                        <div data-quill className="@container/canvas-scene relative flex min-h-0 flex-1">
                            <main className="min-w-0 flex-1">
                                <CanvasBody />
                            </main>
                            {sidePanelOpen && (
                                // A narrow scene overlays the panel on the canvas. A wide one gives it its own column.
                                <aside
                                    className="absolute inset-y-0 right-0 z-10 flex w-full max-w-96 flex-col border-l border-border bg-background shadow-lg @min-[48rem]/canvas-scene:static @min-[48rem]/canvas-scene:w-96 @min-[48rem]/canvas-scene:shrink-0 @min-[48rem]/canvas-scene:shadow-none"
                                    data-attr="canvas-side-panel"
                                >
                                    <CanvasSidePanel canvasId={id} />
                                </aside>
                            )}
                            <CanvasSelectionCommentAction />
                            <CanvasHistoryConfirmDialog />
                        </div>
                    </SceneContent>
                </BindLogic>
            </BindLogic>
        </BindLogic>
    )
}
