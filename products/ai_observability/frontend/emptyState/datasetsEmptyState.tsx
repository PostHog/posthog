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
                headline: 'Build the test set your AI is graded against',
                lead: 'Datasets collect real inputs and the outputs you expect for them. Add items by hand or save them straight from traces, then run prompts and models against the whole set in the playground and offline evaluations to see what changed.',
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
