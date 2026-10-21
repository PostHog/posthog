import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { OfflineEvaluationsTabs } from './OfflineEvaluationsTabs'

const meta: Meta<typeof OfflineEvaluationsTabs> = {
    title: 'Scenes-App/AI observability/Offline experiments/Navigation',
    component: OfflineEvaluationsTabs,
    args: { activeTab: 'datasets' },
    parameters: {
        pageUrl: urls.aiObservabilityDataset('example-dataset'),
        featureFlags: [FEATURE_FLAGS.LLM_ANALYTICS_DATASETS, FEATURE_FLAGS.AI_OBSERVABILITY_OFFLINE_EVALUATIONS],
    },
}
export default meta

type Story = StoryObj<typeof OfflineEvaluationsTabs>

export const DatasetDetail: Story = {}
export const DatasetsOnly: Story = {
    parameters: {
        featureFlags: {
            [FEATURE_FLAGS.LLM_ANALYTICS_DATASETS]: true,
            [FEATURE_FLAGS.AI_OBSERVABILITY_OFFLINE_EVALUATIONS]: false,
        },
    },
}
