import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconCheckCircle, IconPin, IconPinFilled, IconRefresh, IconWarning, IconX } from '@posthog/icons'
import { Badge, Button, Spinner, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import {
    activeCanvasBuild,
    currentHeadBuildFailure,
    formatBuildElapsed,
    latestFinishedCanvasBuild,
    topBuildErrors,
} from './canvasBuildLifecycle'
import { canvasSceneLogic } from './canvasSceneLogic'

// A progress hint, not a stopwatch.
const ELAPSED_TICK_MS = 5000

function IconAction({
    label,
    onClick,
    disabled,
    dataAttr,
    children,
}: {
    label: string
    onClick: () => void
    disabled: boolean
    dataAttr: string
    children: JSX.Element
}): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger
                delay={0}
                render={
                    <Button
                        size="icon-sm"
                        variant="default"
                        aria-label={label}
                        disabled={disabled}
                        onClick={onClick}
                        data-attr={dataAttr}
                    />
                }
            >
                {children}
            </TooltipTrigger>
            <TooltipContent>{label}</TooltipContent>
        </Tooltip>
    )
}

/**
 * The build lifecycle beside the canvas name: progress with elapsed time while a build runs,
 * the errors and a fix or retry when the head's build failed, and pinning for the live build.
 */
export function CanvasBuildStatus(): JSX.Element | null {
    const { builds, view, buildActionPending, fixRequestPending } = useValues(canvasSceneLogic)
    const { buildAction, requestFix } = useActions(canvasSceneLogic)
    const active = builds ? activeCanvasBuild(builds) : null
    const [, setTick] = useState(0)

    // The label reads the clock during render, so the interval only forces a re-render.
    useEffect(() => {
        if (!active?.id) {
            return
        }
        const id = setInterval(() => setTick((tick) => tick + 1), ELAPSED_TICK_MS)
        return () => clearInterval(id)
    }, [active?.id])

    if (!builds) {
        return view?.has_active_build ? (
            <div className="flex items-center gap-1.5" data-attr="canvas-build-status">
                <Spinner />
                <Text size="xs" variant="muted">
                    Building
                </Text>
            </div>
        ) : null
    }

    if (active) {
        return (
            <div className="flex items-center gap-1 whitespace-nowrap" data-attr="canvas-build-status">
                <Spinner />
                <Text size="xs" variant="muted">
                    {active.build_status === 'queued' ? 'Queued' : 'Building'}
                </Text>
                <Text size="xs" variant="muted" translate="no">
                    {formatBuildElapsed(Date.now() - Date.parse(active.created_at))}
                </Text>
                {active.build_status === 'queued' && (
                    <IconAction
                        label="Cancel build"
                        onClick={() => buildAction('cancel', active.id)}
                        disabled={buildActionPending}
                        dataAttr="canvas-build-cancel"
                    >
                        <IconX />
                    </IconAction>
                )}
            </div>
        )
    }

    const failedHead = currentHeadBuildFailure(builds)
    const latest = failedHead ?? latestFinishedCanvasBuild(builds)
    if (!latest) {
        return view?.current_version_id ? (
            <Tooltip>
                <TooltipTrigger render={<span className="inline-flex" />}>
                    <Badge variant="default" data-attr="canvas-build-status">
                        Draft
                    </Badge>
                </TooltipTrigger>
                <TooltipContent>This canvas hasn't been built yet.</TooltipContent>
            </Tooltip>
        ) : null
    }

    if (latest.build_status === 'failed') {
        const errors = topBuildErrors(latest.diagnostics)
        return (
            <div className="flex flex-wrap items-center gap-1" data-attr="canvas-build-status">
                <Tooltip>
                    <TooltipTrigger render={<span className="inline-flex items-center gap-1" />}>
                        <IconWarning className="text-destructive-foreground" />
                        <Text size="xs" variant="destructive">
                            Build failed
                        </Text>
                    </TooltipTrigger>
                    <TooltipContent>
                        <span className="block max-w-sm whitespace-pre-wrap break-words">
                            {[
                                builds.published_build_id
                                    ? "The latest version didn't build. The last working version stays live."
                                    : "This version didn't build, so the canvas shows its source as a draft.",
                                ...errors,
                            ].join('\n')}
                        </span>
                    </TooltipContent>
                </Tooltip>
                <Button
                    size="xs"
                    variant="outline"
                    loading={fixRequestPending}
                    onClick={() => requestFix({ buildId: latest.id })}
                    data-attr="canvas-build-ask-fix"
                >
                    Ask agent to fix
                </Button>
                <IconAction
                    label="Retry build"
                    onClick={() => buildAction('retry', latest.id)}
                    disabled={buildActionPending}
                    dataAttr="canvas-build-retry"
                >
                    <IconRefresh />
                </IconAction>
            </div>
        )
    }

    const published = builds.builds.find((build) => build.id === builds.published_build_id)
    if (published && published.id === latest.id) {
        return (
            <div className="flex items-center gap-0.5" data-attr="canvas-build-status">
                <Tooltip>
                    <TooltipTrigger render={<span className="inline-flex items-center gap-1" />}>
                        <IconCheckCircle className="text-success-foreground" />
                        <Text size="xs" variant="muted">
                            Live
                        </Text>
                    </TooltipTrigger>
                    <TooltipContent>Everyone with access sees this build.</TooltipContent>
                </Tooltip>
                <IconAction
                    label={published.pinned ? 'Unpin build' : 'Pin build'}
                    onClick={() => buildAction(published.pinned ? 'unpin' : 'pin', published.id)}
                    disabled={buildActionPending}
                    dataAttr={published.pinned ? 'canvas-build-unpin' : 'canvas-build-pin'}
                >
                    {published.pinned ? <IconPinFilled /> : <IconPin />}
                </IconAction>
            </div>
        )
    }

    if (published?.pinned && latest.build_status === 'ready') {
        return (
            <div className="flex items-center gap-0.5" data-attr="canvas-build-status">
                <Tooltip>
                    <TooltipTrigger render={<span className="inline-flex" />}>
                        <Text size="xs" variant="muted">
                            Newer build available
                        </Text>
                    </TooltipTrigger>
                    <TooltipContent>A newer build is ready, but an older build is pinned live.</TooltipContent>
                </Tooltip>
                <IconAction
                    label="Unpin build"
                    onClick={() => buildAction('unpin', published.id)}
                    disabled={buildActionPending}
                    dataAttr="canvas-build-unpin"
                >
                    <IconPinFilled />
                </IconAction>
            </div>
        )
    }
    return null
}
