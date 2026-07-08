import type { ReactNode } from 'react'

import { IconBolt } from '@posthog/icons'

import { getPermissionRequestToolInput, registerToolRenderers } from 'products/posthog_ai/frontend/api/tools'
import type { PermissionRequestRecord } from 'products/posthog_ai/frontend/api/types'

import { HogFunctionConfigDiff } from './HogFunctionConfigDiff'
import { buildHogFunctionConfigDiff } from './hogFunctionConfigDiff'
import { hogFunctionConfigurationLogic } from './hogFunctionConfigurationLogic'

/**
 * Approval-card preview for `cdp-functions-partial-update`: a diff of the agent's proposed update
 * against the hog function the user has open. Reads the mounted `hogFunctionConfigurationLogic` for the
 * live config; when the scene isn't mounted there's no current config to diff against, so it returns
 * null and the surface falls back to the raw JSON payload. `findAllMounted` (not `findMounted`) because
 * the logic is keyed by function id — the surface can't reconstruct the key — and the edit scene mounts
 * a single instance.
 */
function renderPartialUpdatePreview(record: PermissionRequestRecord): ReactNode | null {
    const mounted = hogFunctionConfigurationLogic.findAllMounted()[0]
    const current = mounted?.values.configuration as Record<string, unknown> | undefined
    if (!current) {
        return null
    }
    const proposed = getPermissionRequestToolInput(record)
    const diffs = buildHogFunctionConfigDiff(current, proposed)
    if (diffs.length === 0) {
        return null
    }
    return <HogFunctionConfigDiff diffs={diffs} />
}

// Register on module load (idempotent — re-registering the same key overwrites). A preview-only entry:
// no `Renderer`, so the tool-result card still resolves to the generic MCP card via `lookupToolRenderer`.
// cdp-functions-create is intentionally left to the default JSON payload (no current config to diff).
registerToolRenderers([
    {
        key: 'cdp-functions-partial-update',
        displayName: 'Update function',
        icon: <IconBolt />,
        renderPermissionPreview: renderPartialUpdatePreview,
    },
])
