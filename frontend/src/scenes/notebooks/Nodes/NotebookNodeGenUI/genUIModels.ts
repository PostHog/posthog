import type { LemonSelectOptions } from '@posthog/lemon-ui'

import type { GenUIGenerateRequestApi } from 'products/notebooks/frontend/generated/api.schemas'

export type GenUIModel = NonNullable<GenUIGenerateRequestApi['model']>

export const DEFAULT_GENUI_MODEL: GenUIModel = 'claude-sonnet-4-6'

export type GenUIModelInfo = {
    name: string
    estimateLabel: string
    estimatedSeconds: number
}

export const GENUI_MODEL_INFO: Record<GenUIModel, GenUIModelInfo> = {
    'claude-haiku-4-5': {
        name: 'Claude Haiku 4.5',
        estimateLabel: '~1 min',
        estimatedSeconds: 60,
    },
    'claude-sonnet-4-6': {
        name: 'Claude Sonnet 4.6',
        estimateLabel: '~2 min',
        estimatedSeconds: 120,
    },
    'claude-sonnet-5': {
        name: 'Claude Sonnet 5',
        estimateLabel: '~3 min',
        estimatedSeconds: 180,
    },
    'claude-opus-5': {
        name: 'Claude Opus 5',
        estimateLabel: '~5 min',
        estimatedSeconds: 300,
    },
}

export function isGenUIModel(model: string | null | undefined): model is GenUIModel {
    return model !== null && model !== undefined && model in GENUI_MODEL_INFO
}

export const GENUI_MODEL_OPTIONS: LemonSelectOptions<GenUIModel> = [
    {
        value: 'claude-haiku-4-5',
        label: `Fast - ${GENUI_MODEL_INFO['claude-haiku-4-5'].name} (${GENUI_MODEL_INFO['claude-haiku-4-5'].estimateLabel})`,
        tooltip: 'Returns simpler visualizations more quickly.',
    },
    {
        value: 'claude-sonnet-4-6',
        label: `Balanced - ${GENUI_MODEL_INFO['claude-sonnet-4-6'].name} (${GENUI_MODEL_INFO['claude-sonnet-4-6'].estimateLabel})`,
        tooltip: 'Balances generation time and visual detail.',
    },
    {
        value: 'claude-sonnet-5',
        label: `High quality - ${GENUI_MODEL_INFO['claude-sonnet-5'].name} (${GENUI_MODEL_INFO['claude-sonnet-5'].estimateLabel})`,
        tooltip: 'Produces more detailed visualizations and may take longer.',
    },
    {
        value: 'claude-opus-5',
        label: `Highest quality - ${GENUI_MODEL_INFO['claude-opus-5'].name} (${GENUI_MODEL_INFO['claude-opus-5'].estimateLabel})`,
        tooltip: 'Produces the most detailed visualizations and may take the longest.',
    },
]
