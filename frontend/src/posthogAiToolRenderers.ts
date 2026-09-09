import { posthogAiToolRenderers as cdpToolRenderers } from 'products/cdp/frontend/posthogAiToolRenderers'
import { posthogAiToolRenderers as logsToolRenderers } from 'products/logs/frontend/posthogAiToolRenderers'
import { posthogAiToolRenderers as dataToolRenderers } from 'products/posthog_ai/frontend/api/posthogAiToolRenderers'
import type { ToolRegistryEntry } from 'products/posthog_ai/frontend/api/tools'

export const posthogAiToolRenderers: ToolRegistryEntry[] = [...dataToolRenderers, ...cdpToolRenderers, ...logsToolRenderers]
