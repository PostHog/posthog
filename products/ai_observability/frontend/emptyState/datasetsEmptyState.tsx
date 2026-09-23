import * as researchPng from '@posthog/brand/hoggies/png/research'
import { IconDocument } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { DatasetsPreview } from './DatasetsPreview'
import { datasetsSetupLogic } from './datasetsSetupLogic'

const HedgehogResearch = pngHoggie(researchPng)

export const datasetsEmptyState: SceneProductEmptyState = {
    statusLogic: datasetsSetupLogic,
    config: {
        productKey: ProductKey.LLM_DATASETS,
        productName: 'Datasets',
        icon: <IconDocument />,
        accentColor: 'var(--color-product-llm-datasets-light)',
        accentColorDark: 'var(--color-product-llm-analytics-dark)',
        hedgehog: HedgehogResearch,
        text: {
            'needs-setup': {
                headline: 'Check changes before they reach production',
                lead: 'Datasets are the input and output pairs you expect from your AI. Add items manually or save them from production traces. Then pull them in wherever you test changes to catch regressions before they go live.',
            },
        },
        primaryAction: {
            label: 'Create your first dataset',
            to: urls.aiObservabilityDataset('new'),
            accessControl: {
                resourceType: AccessControlResourceType.LlmAnalytics,
                minAccessLevel: AccessControlLevel.Editor,
            },
            dataAttr: 'create-dataset-button',
        },
        docsUrl: 'https://posthog.com/docs/ai-evals/datasets',
        skippable: false,
        previewLabel: 'Your datasets, once filled',
        Preview: DatasetsPreview,
    },
}
