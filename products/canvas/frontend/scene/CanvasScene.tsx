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

import { CanvasGenerateHero } from './CanvasGenerateHero'
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
    const { bodyState, viewLoading } = useValues(canvasSceneLogic)
    const { loadView } = useActions(canvasSceneLogic)

    switch (bodyState) {
        case 'loading':
            return (
                <div className="flex h-full flex-col gap-3 p-6">
                    <Skeleton className="h-8 w-1/3" />
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
            return <CanvasGenerateHero />
        case 'generation-ended':
            return (
                <CanvasGenerateHero notice="The last run finished without a canvas to show. Describe it again to start a new run." />
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
            return <CanvasRenderer />
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
            <div data-quill className="@container/canvas-scene flex h-full min-h-0 flex-col bg-background">
                <CanvasSceneHeader />
                <div className="flex min-h-0 flex-1">
                    <main className="min-w-0 flex-1">
                        <CanvasBody />
                    </main>
                    {sidePanelOpen && (
                        // The side panel (chat, timeline, comments, versions) mounts here.
                        <aside className="w-96 shrink-0 border-l border-border" data-attr="canvas-side-panel" />
                    )}
                </div>
            </div>
        </BindLogic>
    )
}
