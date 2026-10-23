import { useActions, useValues } from 'kea'
import { ReactNode, useEffect, useState } from 'react'

import { IconPin, IconPinFilled, IconRefresh, IconX } from '@posthog/icons'
import { Badge, Button, Spinner, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import {
    activeCanvasBuild,
    currentHeadBuildFailure,
    formatBuildElapsed,
    latestFinishedCanvasBuild,
    topBuildErrors,
} from './canvasBuildLifecycle'
import { canvasSceneLogic } from './canvasSceneLogic'
import { CanvasStatusIssue } from './CanvasStatusIssue'

// A progress hint, not a stopwatch.
const ELAPSED_TICK_MS = 5000

function IconAction({
    label,
    onClick,
    disabled,
    pressed,
    dataAttr,
    children,
}: {
    label: string
    onClick: () => void
    disabled: boolean
    pressed?: boolean
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
                        aria-pressed={pressed}
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

function StatusBadge({
    variant,
    hint,
    children,
}: {
    variant: 'default' | 'info' | 'success' | 'warning'
    hint: string
    children: ReactNode
}): JSX.Element {
    return (
        <Tooltip>
            {/* quill's Badge does not forward refs under React 18, so a span anchors the tooltip. */}
            <TooltipTrigger render={<span className="inline-flex" />}>
                <Badge variant={variant}>{children}</Badge>
            </TooltipTrigger>
            <TooltipContent>{hint}</TooltipContent>
        </Tooltip>
    )
}

/**
 * The build lifecycle in the canvas header: progress with elapsed time while a build runs,
 * what failed and how to fix it when the head's build failed, and pinning for the live build.
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
            <div className="flex items-center" data-attr="canvas-build-status">
                <Badge variant="info">
                    <Spinner />
                    Building
                </Badge>
            </div>
        ) : null
    }

    if (active) {
        return (
            <div className="flex items-center gap-1" data-attr="canvas-build-status">
                <StatusBadge variant="info" hint="A new version is building. The canvas updates when it's ready.">
                    <Spinner />
                    <span>{active.build_status === 'queued' ? 'Queued' : 'Building'}</span>
                    <span translate="no">{formatBuildElapsed(Date.now() - Date.parse(active.created_at))}</span>
                </StatusBadge>
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

    const failedHead = currentHeadBuildFailure({ ...builds, current_version_id: view?.current_version_id ?? null })
    const latest =
        failedHead ??
        latestFinishedCanvasBuild({
            ...builds,
            builds: builds.builds.filter((build) => build.build_status === 'ready'),
        })
    if (!latest) {
        return view?.current_version_id ? (
            <div className="flex items-center" data-attr="canvas-build-status">
                <StatusBadge variant="default" hint="This canvas hasn't been built yet.">
                    Draft
                </StatusBadge>
            </div>
        ) : null
    }

    if (latest.build_status === 'failed') {
        return (
            <div className="flex items-center" data-attr="canvas-build-status">
                <CanvasStatusIssue
                    label="Build failed"
                    title="The latest version didn't build"
                    description={
                        builds.published_build_id
                            ? 'The last working version stays live. Ask the agent to fix the errors, or retry the build.'
                            : 'The canvas shows its source as a draft until a build works. Ask the agent to fix the errors, or retry the build.'
                    }
                    details={topBuildErrors(latest.diagnostics)}
                    dataAttr="canvas-build-failed-details"
                    actions={
                        <>
                            <Button
                                size="sm"
                                variant="outline"
                                loading={buildActionPending}
                                onClick={() => buildAction('retry', latest.id)}
                                data-attr="canvas-build-retry"
                            >
                                <IconRefresh />
                                Retry build
                            </Button>
                            <Button
                                size="sm"
                                variant="primary"
                                loading={fixRequestPending}
                                onClick={() => requestFix({ buildId: latest.id })}
                                data-attr="canvas-build-ask-fix"
                            >
                                Ask agent to fix
                            </Button>
                        </>
                    }
                />
            </div>
        )
    }

    const published = builds.builds.find((build) => build.id === builds.published_build_id)
    if (published && published.id === latest.id) {
        return (
            <div className="flex items-center gap-1" data-attr="canvas-build-status">
                <StatusBadge
                    variant="success"
                    hint={
                        published.pinned
                            ? 'Everyone with access sees this build. It stays live until you unpin it.'
                            : 'Everyone with access sees this build.'
                    }
                >
                    Live
                </StatusBadge>
                <IconAction
                    label={published.pinned ? 'Unpin build' : 'Pin build'}
                    pressed={published.pinned}
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
            <div className="flex items-center gap-1" data-attr="canvas-build-status">
                <StatusBadge
                    variant="warning"
                    hint="A newer build is ready, but an older build is pinned live. Unpin it to show the newer one."
                >
                    Pinned
                </StatusBadge>
                <IconAction
                    label="Unpin build"
                    pressed
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
