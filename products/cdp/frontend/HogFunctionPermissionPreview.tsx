import { HogFunctionConfigDiff } from 'scenes/hog-functions/configuration/HogFunctionConfigDiff'
import { buildHogFunctionConfigDiff } from 'scenes/hog-functions/configuration/hogFunctionConfigDiffUtils'
import { hogFunctionConfigurationLogic } from 'scenes/hog-functions/configuration/hogFunctionConfigurationLogic'

import { getPermissionRequestToolInput, type PermissionPreviewProps } from 'products/posthog_ai/frontend/api/tools'

/**
 * Approval-card preview for `cdp-functions-partial-update`: a diff of the agent's proposed update
 * against the hog function the user has open. Reads the mounted `hogFunctionConfigurationLogic` for the
 * live config; when the scene isn't mounted, or its config has not loaded yet, there's nothing to diff
 * against, so it returns the evidence fallback without mounting or fetching the scene. `findAllMounted`
 * (not `findMounted`) because the logic is keyed by function id — the surface can't reconstruct the key —
 * and the edit scene mounts a single instance.
 */
export function HogFunctionPermissionPreview({ request, fallback }: PermissionPreviewProps): JSX.Element {
    const mounted = hogFunctionConfigurationLogic.findAllMounted()[0]
    const current = mounted?.values.configuration as Record<string, unknown> | undefined
    // The scene mounts with an empty form and fills it when its fetch lands. A diff against that empty
    // config marks every proposed field as newly added, hiding the values the update replaces.
    if (!mounted?.values.loaded || !current || Object.keys(current).length === 0) {
        return <>{fallback}</>
    }
    const proposed = getPermissionRequestToolInput(request)
    // An update aimed at a different function than the one on screen must not render a diff against
    // the open form — that would preview the wrong change. Both ids must be known and match, because
    // a new-function form carries no id and would otherwise diff against template defaults.
    const targetId = typeof proposed.id === 'string' ? proposed.id : null
    const mountedId = typeof mounted.props.id === 'string' ? mounted.props.id : null
    if (!targetId || !mountedId || targetId !== mountedId) {
        return <>{fallback}</>
    }
    const diffs = buildHogFunctionConfigDiff(current, proposed)
    if (diffs.length === 0) {
        return <>{fallback}</>
    }
    return (
        <div className="max-h-80 overflow-y-auto">
            <HogFunctionConfigDiff diffs={diffs} />
        </div>
    )
}
