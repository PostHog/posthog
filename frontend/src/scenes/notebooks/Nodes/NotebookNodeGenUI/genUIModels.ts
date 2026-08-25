import type { LemonSelectOptions } from '@posthog/lemon-ui'

import type { GenUIGenerateRequestApi } from 'products/notebooks/frontend/generated/api.schemas'

export type GenUIModel = NonNullable<GenUIGenerateRequestApi['model']>

export const DEFAULT_GENUI_MODEL: GenUIModel = 'claude-sonnet-4-6'

export const GENUI_MODEL_OPTIONS: LemonSelectOptions<GenUIModel> = [
    {
        value: 'claude-haiku-4-5',
        label: 'Fast - Claude Haiku 4.5',
        tooltip: 'Returns simpler visualizations more quickly.',
    },
    {
        value: 'claude-sonnet-4-6',
        label: 'Balanced - Claude Sonnet 4.6',
        tooltip: 'Balances generation time and visual detail.',
    },
    {
        value: 'claude-sonnet-5',
        label: 'Best quality - Claude Sonnet 5',
        tooltip: 'Produces more detailed visualizations and may take longer.',
    },
]
