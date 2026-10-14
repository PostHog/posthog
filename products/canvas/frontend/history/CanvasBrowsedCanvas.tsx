import { useActions, useValues } from 'kea'

import { IconClock } from '@posthog/icons'
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

import { CanvasRenderer } from '../scene/CanvasRenderer'
import { canvasSceneLogic } from '../scene/canvasSceneLogic'
import { CanvasBrowseBanner } from './CanvasBrowseBanner'
import { canvasHistoryLogic } from './canvasHistoryLogic'

/** A previous version or a draft, rendered from its retained build or, failing that, its source. */
export function CanvasBrowsedCanvas(): JSX.Element {
    const { browseVersionId, browsedRender, browsedRenderLoading, browsedDraft } = useValues(canvasHistoryLogic)
    const { setBrowseVersion, loadBrowsedRender } = useActions(canvasHistoryLogic)
    const { sandboxDocumentUrl } = useValues(canvasSceneLogic)
    const render = browsedRender?.versionId === browseVersionId ? browsedRender : null
    const renderable =
        !!render &&
        (!!render.build?.artifact_url || (!!render.project?.files['src/canvas.tsx'] && !!sandboxDocumentUrl))

    return (
        <div className="flex h-full min-h-0 flex-col">
            <CanvasBrowseBanner />
            <div className="min-h-0 flex-1">
                {!render ? (
                    browsedRenderLoading ? (
                        <div className="flex h-full flex-col gap-3 p-6">
                            <Skeleton className="h-8 w-1/3" />
                            <Skeleton className="h-full w-full" />
                        </div>
                    ) : (
                        <Empty className="h-full border-0">
                            <EmptyHeader>
                                <EmptyTitle>This version didn't load</EmptyTitle>
                                <EmptyDescription>Check your connection and try again.</EmptyDescription>
                            </EmptyHeader>
                            <EmptyContent>
                                <Button
                                    variant="outline"
                                    onClick={() => browseVersionId && loadBrowsedRender({ versionId: browseVersionId })}
                                >
                                    Try again
                                </Button>
                            </EmptyContent>
                        </Empty>
                    )
                ) : renderable ? (
                    <CanvasRenderer
                        // A fresh frame per version, so one version's state never leaks into another.
                        key={render.versionId}
                        source={{
                            sourceVersionId: render.versionId,
                            build: render.build?.artifact_url ? render.build : null,
                            draftSource: render.project,
                        }}
                    />
                ) : (
                    <Empty className="h-full border-0">
                        <EmptyHeader>
                            <EmptyMedia variant="icon">
                                <IconClock />
                            </EmptyMedia>
                            <EmptyTitle>No preview for this version</EmptyTitle>
                            <EmptyDescription>
                                {browsedDraft
                                    ? "This draft hasn't built yet and can't render from its source here. Publish it to build it."
                                    : "This version has no saved build and can't render from its source here. Revert to it to rebuild it."}
                            </EmptyDescription>
                        </EmptyHeader>
                        <EmptyContent>
                            <Button variant="outline" onClick={() => setBrowseVersion(null)}>
                                {browsedDraft ? 'Back to live' : 'Back to latest'}
                            </Button>
                        </EmptyContent>
                    </Empty>
                )}
            </div>
        </div>
    )
}
