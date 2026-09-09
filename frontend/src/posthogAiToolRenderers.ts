import { posthogAiToolRenderers as cdpToolRenderers } from 'products/cdp/frontend/posthogAiToolRenderers'
import { posthogAiToolRenderers as errorTrackingToolRenderers } from 'products/error_tracking/frontend/posthogAiToolRenderers'
import { posthogAiToolRenderers as logsToolRenderers } from 'products/logs/frontend/posthogAiToolRenderers'
import type { ToolRegistryEntry } from 'products/posthog_ai/frontend/api/tools'
import { posthogAiToolRenderers as dataToolRenderers } from 'products/posthog_ai/frontend/posthogAiToolRenderers'

export const posthogAiToolRenderers: ToolRegistryEntry[] = [
    ...dataToolRenderers,
    ...cdpToolRenderers,
    ...errorTrackingToolRenderers,
    ...logsToolRenderers,
]
