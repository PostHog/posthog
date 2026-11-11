import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconClock, IconPencil, IconSparkles, IconUser } from '@posthog/icons'
import {
    Badge,
    Button,
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Skeleton,
    Text,
} from '@posthog/quill'

import type { CanvasBuildApi } from '../../generated/api.schemas'
import {
    canvasBuildStatusBadgeVariant,
    canvasBuildStatusLabel,
    canvasDraftByline,
    canvasDraftTitle,
    canvasVersionByline,
    canvasVersionTitle,
} from '../../history/canvasHistoryLabels'
import { canvasHistoryLogic } from '../../history/canvasHistoryLogic'
import { CanvasTimelineRow } from './CanvasTimelineRow'

/** The Timeline tab: staged drafts, then every published version and how its build went. */
export function CanvasTimelineTab(): JSX.Element {
    const {
        versions,
        versionsLoading,
        drafts,
        headVersionId,
        browseVersionId,
        versionLabels,
        buildHistory,
        displayedVersionId,
    } = useValues(canvasHistoryLogic)
    const { loadBuildHistory, setBrowseVersion, requestConfirmation } = useActions(canvasHistoryLogic)

    useEffect(() => {
        loadBuildHistory()
    }, [loadBuildHistory])

    // Builds come newest first, so the first one per version is its latest attempt.
    const latestBuildByVersion = new Map<string, CanvasBuildApi>()
    for (const build of buildHistory?.builds ?? []) {
        if (!latestBuildByVersion.has(build.source_version_id)) {
            latestBuildByVersion.set(build.source_version_id, build)
        }
    }

    if (versions.length === 0 && drafts.length === 0) {
        return versionsLoading ? (
            <div className="flex flex-col gap-2 p-3">
                <Skeleton className="h-3 w-16" />
                <Skeleton className="h-14 w-full" />
                <Skeleton className="h-14 w-full" />
                <Skeleton className="h-14 w-full" />
            </div>
        ) : (
            <Empty className="h-full border-0">
                <EmptyHeader>
                    <EmptyMedia variant="icon">
                        <IconClock />
                    </EmptyMedia>
                    <EmptyTitle>No changes yet</EmptyTitle>
                    <EmptyDescription>
                        Each version of this canvas shows here, whether you or an agent made it.
                    </EmptyDescription>
                </EmptyHeader>
            </Empty>
        )
    }

    return (
        <div className="flex h-full min-h-0 flex-col gap-4 overflow-y-auto p-3" data-attr="canvas-timeline">
            {drafts.length > 0 && (
                <section aria-labelledby="canvas-timeline-drafts" className="flex flex-col gap-2">
                    <Text id="canvas-timeline-drafts" size="xs" variant="muted" weight="medium" render={<h3 />}>
                        Drafts
                    </Text>
                    <div role="list" className="flex flex-col">
                        {drafts.map((draft) => (
                            <CanvasTimelineRow
                                key={draft.version_id}
                                icon={<IconPencil />}
                                title={canvasDraftTitle(draft)}
                                meta={canvasDraftByline(draft)}
                                badges={
                                    <Badge variant={canvasBuildStatusBadgeVariant(draft.build_status)}>
                                        {canvasBuildStatusLabel(draft.build_status)}
                                    </Badge>
                                }
                                viewing={draft.version_id === browseVersionId}
                                draft
                                onOpen={() => setBrowseVersion(draft.version_id)}
                                action={
                                    <Button
                                        size="xs"
                                        variant="outline"
                                        onClick={() =>
                                            requestConfirmation({ kind: 'promote', versionId: draft.version_id })
                                        }
                                        data-attr="canvas-timeline-promote"
                                    >
                                        Publish…
                                    </Button>
                                }
                                dataAttr="canvas-timeline-draft"
                            />
                        ))}
                    </div>
                </section>
            )}
            <section aria-labelledby="canvas-timeline-versions" className="flex flex-col gap-2">
                <Text id="canvas-timeline-versions" size="xs" variant="muted" weight="medium" render={<h3 />}>
                    Versions
                </Text>
                <div role="list" className="flex flex-col">
                    {versions.map((version) => {
                        const build = latestBuildByVersion.get(version.id)
                        const live = version.id === headVersionId
                        return (
                            <CanvasTimelineRow
                                key={version.id}
                                icon={version.task_id ? <IconSparkles /> : <IconUser />}
                                label={versionLabels[version.id]}
                                title={canvasVersionTitle(version)}
                                meta={canvasVersionByline(version)}
                                badges={
                                    live || (build && build.build_status !== 'ready') ? (
                                        <>
                                            {live && <Badge variant="success">Live</Badge>}
                                            {build && build.build_status !== 'ready' && (
                                                <Badge variant={canvasBuildStatusBadgeVariant(build.build_status)}>
                                                    {canvasBuildStatusLabel(build.build_status)}
                                                </Badge>
                                            )}
                                        </>
                                    ) : undefined
                                }
                                viewing={version.id === displayedVersionId}
                                live={live}
                                onOpen={() => setBrowseVersion(live ? null : version.id)}
                                action={
                                    live ? null : (
                                        <Button
                                            size="xs"
                                            variant="outline"
                                            onClick={() =>
                                                requestConfirmation({ kind: 'revert', versionId: version.id })
                                            }
                                            data-attr="canvas-timeline-revert"
                                        >
                                            Revert…
                                        </Button>
                                    )
                                }
                                dataAttr="canvas-timeline-version"
                            />
                        )
                    })}
                </div>
            </section>
        </div>
    )
}
