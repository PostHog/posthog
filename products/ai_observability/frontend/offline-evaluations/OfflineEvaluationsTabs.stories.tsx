import type { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { OfflineEvaluationsTabs } from './OfflineEvaluationsTabs'
import { OfflineExperimentsScene } from './OfflineExperimentsScene'

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
export const DatasetsUnavailable: Story = {
    render: () => <OfflineExperimentsScene />,
    parameters: {
        pageUrl: urls.aiObservabilityDatasets(),
        featureFlags: {
            [FEATURE_FLAGS.LLM_ANALYTICS_DATASETS]: false,
            [FEATURE_FLAGS.AI_OBSERVABILITY_OFFLINE_EVALUATIONS]: true,
        },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await canvas.findByText('Datasets are coming soon.')
        const datasetsTab = canvas.getByRole('button', { name: 'Datasets' })
        if (!datasetsTab.hasAttribute('disabled') && datasetsTab.getAttribute('aria-disabled') !== 'true') {
            throw new Error('Datasets must stay disabled when the feature flag is off')
        }
    },
}
