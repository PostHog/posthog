import { useValues } from 'kea'

import { Badge, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { canvasSceneLogic } from './canvasSceneLogic'

/** A compact read of the canvas's build lifecycle, beside its name. */
export function CanvasBuildStatusBadge(): JSX.Element | null {
    const { buildStatus, view } = useValues(canvasSceneLogic)

    if (buildStatus === 'building') {
        return <StatusBadge variant="info" label="Building" hint="A new version is building." />
    }
    if (buildStatus === 'failed') {
        return (
            <StatusBadge
                variant="destructive"
                label="Build failed"
                hint={
                    view?.published_build
                        ? "The latest version didn't build. The last working version stays live."
                        : "This version didn't build, so the canvas shows its source as a draft."
                }
            />
        )
    }
    if (buildStatus === 'live') {
        return <StatusBadge variant="success" label="Live" hint="Everyone with access sees this version." />
    }
    if (view?.current_version_id) {
        return <StatusBadge variant="default" label="Draft" hint="This canvas has not been built yet." />
    }
    return null
}

function StatusBadge({
    variant,
    label,
    hint,
}: {
    variant: 'info' | 'destructive' | 'success' | 'default'
    label: string
    hint: string
}): JSX.Element {
    return (
        <Tooltip>
            {/* quill's Badge does not forward refs under React 18, so a span anchors the tooltip. */}
            <TooltipTrigger render={<span className="inline-flex" />}>
                <Badge variant={variant} data-attr="canvas-build-status">
                    {label}
                </Badge>
            </TooltipTrigger>
            <TooltipContent>{hint}</TooltipContent>
        </Tooltip>
    )
}
