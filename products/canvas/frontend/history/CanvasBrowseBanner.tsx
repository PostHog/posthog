import { useActions, useValues } from 'kea'

import { IconClock, IconPencil } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { canvasVersionByline } from './canvasHistoryLabels'
import { canvasHistoryLogic } from './canvasHistoryLogic'

/** The strip above a browsed version or draft: what it is, how to leave it, and how to make it live. */
export function CanvasBrowseBanner(): JSX.Element | null {
    const { browseVersionId, browsedDraft, browsedVersion, versionLabels } = useValues(canvasHistoryLogic)
    const { setBrowseVersion, requestConfirmation } = useActions(canvasHistoryLogic)

    if (!browseVersionId) {
        return null
    }
    const label = versionLabels[browseVersionId]
    const description = browsedDraft
        ? "You're viewing a draft. It isn't live yet."
        : browsedVersion
          ? `You're viewing ${label ?? 'a previous version'}. ${canvasVersionByline(browsedVersion)}`
          : "You're viewing a previous version."

    return (
        <div
            className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-border bg-info px-3 py-1.5"
            data-attr="canvas-browse-banner"
        >
            <div className="flex min-w-0 items-center gap-1.5 text-info-foreground">
                {browsedDraft ? <IconPencil /> : <IconClock />}
                <Text size="xs" className="min-w-0 truncate text-info-foreground">
                    {description}
                </Text>
            </div>
            <div className="flex flex-wrap items-center gap-2">
                {browsedVersion?.task_id && (
                    <Button
                        size="xs"
                        variant="link-muted"
                        render={<LinkPrimitive to={urls.taskDetail(browsedVersion.task_id)} />}
                        data-attr="canvas-browse-open-task"
                    >
                        Open task
                    </Button>
                )}
                <Button
                    size="xs"
                    variant="outline"
                    onClick={() => setBrowseVersion(null)}
                    data-attr="canvas-browse-back"
                >
                    {browsedDraft ? 'Back to live' : 'Back to latest'}
                </Button>
                <Button
                    size="xs"
                    variant="primary"
                    onClick={() =>
                        requestConfirmation({ kind: browsedDraft ? 'promote' : 'revert', versionId: browseVersionId })
                    }
                    data-attr={browsedDraft ? 'canvas-browse-promote' : 'canvas-browse-revert'}
                >
                    {browsedDraft ? 'Publish draft…' : 'Revert to this version…'}
                </Button>
            </div>
        </div>
    )
}
