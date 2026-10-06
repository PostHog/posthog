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
import { useFileSystemLogView } from 'lib/hooks/useFileSystemLogView'
import { cn } from 'lib/utils/css-classes'
import { SceneExport } from 'scenes/sceneTypes'

import { canvasEditLogic } from '../editing/canvasEditLogic'
import { CanvasEditorRenderer } from '../editing/CanvasEditorRenderer'
import { CanvasBrowsedCanvas } from '../history/CanvasBrowsedCanvas'
import { CanvasHistoryConfirmDialog } from '../history/CanvasHistoryConfirmDialog'
import { canvasHistoryLogic } from '../history/canvasHistoryLogic'
import { canvasCommentsLogic } from '../sidePanel/comments/canvasCommentsLogic'
import { CanvasCommentThreadPopover } from '../sidePanel/comments/CanvasCommentThreadPopover'
import { CanvasSelectionCommentAction } from '../sidePanel/comments/CanvasSelectionCommentAction'
import { CanvasEmptyBody } from './CanvasEmptyBody'
import { CanvasFullscreenExit } from './CanvasFullscreenExit'
import { canvasFullscreenLogic } from './canvasFullscreenLogic'
import { CanvasGeneratingState } from './CanvasGeneratingState'
import { CanvasRenderer } from './CanvasRenderer'
import { CanvasSceneHeader } from './CanvasSceneHeader'
import { CanvasSceneLogicProps, canvasSceneLogic } from './canvasSceneLogic'

export const scene: SceneExport<CanvasSceneLogicProps> = {
    component: CanvasScene,
    logic: canvasSceneLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

function CanvasEditBody(): JSX.Element {
    const { entry, sourceError, sourceLoading } = useValues(canvasEditLogic)
    const { loadSource, setEditing } = useActions(canvasEditLogic)

    if (entry) {
        return <CanvasEditorRenderer />
    }
    if (sourceError && !sourceLoading) {
        return (
            <Empty className="h-full border-0">
                <EmptyHeader>
                    <EmptyMedia variant="icon">
                        <IconWarning />
                    </EmptyMedia>
                    <EmptyTitle>This canvas can't be edited right now</EmptyTitle>
                    <EmptyDescription>{sourceError}</EmptyDescription>
                </EmptyHeader>
                <EmptyContent>
                    <div className="flex flex-wrap justify-center gap-2">
                        <Button variant="outline" onClick={() => loadSource()} data-attr="canvas-edit-load-retry">
                            Try again
                        </Button>
                        <Button variant="default" onClick={() => setEditing(false)} data-attr="canvas-edit-cancel">
                            Stop editing
                        </Button>
                    </div>
                </EmptyContent>
            </Empty>
        )
    }
    return (
        <div className="flex h-full flex-col gap-3 p-4" aria-label="Loading the canvas source">
            <Skeleton className="h-4 w-1/3" />
            <Skeleton className="h-full w-full" />
        </div>
    )
}

function CanvasBody(): JSX.Element {
    const { bodyState, viewLoading, liveRenderSource } = useValues(canvasSceneLogic)
    const { loadView } = useActions(canvasSceneLogic)
    const { browseVersionId } = useValues(canvasHistoryLogic)
    const { editing } = useValues(canvasEditLogic)

    if (browseVersionId && bodyState !== 'missing' && bodyState !== 'error') {
        return <CanvasBrowsedCanvas />
    }
    if (editing && bodyState !== 'missing' && bodyState !== 'error') {
        return <CanvasEditBody />
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

function CanvasMain(): JSX.Element {
    const { fullscreen } = useValues(canvasFullscreenLogic)

    return (
        <main
            className={cn(
                'min-h-0 flex-1',
                fullscreen ? 'fixed inset-0 z-[var(--z-drawer)] bg-background' : 'relative'
            )}
        >
            <CanvasBody />
            <CanvasCommentThreadPopover />
            <CanvasFullscreenExit />
        </main>
    )
}

export function CanvasScene({ id }: CanvasSceneLogicProps): JSX.Element {
    const enabled = useFeatureFlag('TODAY_RAIL_NAV')
    const { viewMissing } = useValues(canvasSceneLogic({ id }))
    // Recently opened lists read the view log, so a canvas records its view like a dashboard does.
    useFileSystemLogView({ type: 'canvas', ref: id, enabled: enabled && !viewMissing })

    if (!enabled || viewMissing) {
        return <NotFound object="canvas" />
    }
    return (
        <BindLogic logic={canvasSceneLogic} props={{ id }}>
            <BindLogic logic={canvasHistoryLogic} props={{ id }}>
                <BindLogic logic={canvasCommentsLogic} props={{ id }}>
                    <BindLogic logic={canvasEditLogic} props={{ id }}>
                        <BindLogic logic={canvasFullscreenLogic} props={{ id }}>
                            <div data-quill className="flex h-full min-h-0 flex-col bg-background">
                                <CanvasSceneHeader />
                                <CanvasMain />
                                <CanvasSelectionCommentAction />
                                <CanvasHistoryConfirmDialog />
                            </div>
                        </BindLogic>
                    </BindLogic>
                </BindLogic>
            </BindLogic>
        </BindLogic>
    )
}
