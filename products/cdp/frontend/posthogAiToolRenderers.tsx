import { IconBolt } from '@posthog/icons'

import { lazyWithRetry } from 'lib/utils/retryImport'

import type { ToolRegistryEntry } from 'products/posthog_ai/frontend/api/tools'

export const posthogAiToolRenderers: ToolRegistryEntry[] = [
    {
        key: 'cdp-functions-partial-update',
        displayName: 'Update function',
        icon: <IconBolt />,
        PermissionPreview: lazyWithRetry(() =>
            import('./HogFunctionPermissionPreview').then((m) => ({ default: m.HogFunctionPermissionPreview }))
        ),
        requiresPostHogOrigin: true,
    },
]
