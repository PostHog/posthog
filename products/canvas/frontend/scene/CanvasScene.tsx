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

import { CanvasBrowsedCanvas } from '../history/CanvasBrowsedCanvas'
import { CanvasHistoryConfirmDialog } from '../history/CanvasHistoryConfirmDialog'
import { canvasHistoryLogic } from '../history/canvasHistoryLogic'
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
                <div className="flex h-full flex-col gap-3 p-4">
                    <Skeleton className="h-4 w-1/3" />
                    <Skeleton className="h-full w-full" />
                </div>
            )
        case 'error':
            return (
                <Empty className="h-full border-0">
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
                <Empty className="h-full border-0">
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
    const { viewMissing } = useValues(canvasSceneLogic({ id }))

    if (!enabled || viewMissing) {
        return <NotFound object="canvas" />
    }
    return (
        <BindLogic logic={canvasSceneLogic} props={{ id }}>
            <BindLogic logic={canvasHistoryLogic} props={{ id }}>
                <BindLogic logic={canvasCommentsLogic} props={{ id }}>
                    <div data-quill className="flex h-full min-h-0 flex-col bg-background">
                        <CanvasSceneHeader />
                        <main className="relative min-h-0 flex-1">
                            <CanvasBody />
                        </main>
                        <CanvasSelectionCommentAction />
                        <CanvasHistoryConfirmDialog />
                    </div>
                </BindLogic>
            </BindLogic>
        </BindLogic>
    )
}
