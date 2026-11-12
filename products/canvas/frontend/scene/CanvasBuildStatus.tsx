import { useValues } from 'kea'
import { ReactNode, useEffect, useState } from 'react'

import { Badge, Spinner, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

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
 * what failed when the head's build failed, and whether the live build is pinned.
 */
export function CanvasBuildStatus(): JSX.Element | null {
    const { builds, view } = useValues(canvasSceneLogic)
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
            <div className="flex items-center" data-attr="canvas-build-status">
                <StatusBadge variant="info" hint="A new version is building. The canvas updates when it's ready.">
                    <Spinner />
                    <span>{active.build_status === 'queued' ? 'Queued' : 'Building'}</span>
                    <span translate="no">{formatBuildElapsed(Date.now() - Date.parse(active.created_at))}</span>
                </StatusBadge>
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
                            ? 'The last working version stays live. Ask your agent to fix the errors with the PostHog MCP server.'
                            : 'The canvas shows its source as a draft until a build works. Ask your agent to fix the errors with the PostHog MCP server.'
                    }
                    details={topBuildErrors(latest.diagnostics)}
                    dataAttr="canvas-build-failed-details"
                />
            </div>
        )
    }

    const published = builds.builds.find((build) => build.id === builds.published_build_id)
    if (published && published.id === latest.id) {
        return (
            <div className="flex items-center" data-attr="canvas-build-status">
                <StatusBadge
                    variant="success"
                    hint={
                        published.pinned
                            ? 'Everyone with access sees this build. It stays live until it is unpinned.'
                            : 'Everyone with access sees this build.'
                    }
                >
                    Live
                </StatusBadge>
            </div>
        )
    }

    if (published?.pinned && latest.build_status === 'ready') {
        return (
            <div className="flex items-center" data-attr="canvas-build-status">
                <StatusBadge
                    variant="warning"
                    hint="A newer build is ready, but an older build is pinned live. The newer one shows once the older one is unpinned."
                >
                    Pinned
                </StatusBadge>
            </div>
        )
    }
    return null
}
