import type { Meta, StoryObj } from '@storybook/react'
import { fireEvent, within } from '@testing-library/dom'

import { FEATURE_FLAGS } from 'lib/constants'
import { cn } from 'lib/utils/css-classes'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { OfflineEvaluationsTabs } from './OfflineEvaluationsTabs'
import { OfflineExperimentsScene } from './OfflineExperimentsScene'

const meta: Meta<typeof OfflineEvaluationsTabs> = {
    title: 'Scenes-App/AI observability/Offline experiments/Navigation',
    component: OfflineEvaluationsTabs,
    args: { activeTab: 'datasets' },
    decorators: [
        (Story, { parameters }) => (
            <div className={cn('@container/main-content', parameters.narrow ? 'w-[520px]' : 'w-[1200px]')}>
                <Story />
            </div>
        ),
    ],
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

export const EmptyDatasets: Story = {
    render: () => <OfflineExperimentsScene />,
    parameters: {
        pageUrl: urls.aiObservabilityDatasets(),
        mockDate: '2026-10-01',
        testOptions: { waitForSelector: '[data-attr="create-dataset-button"]' },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team/datasets/': { count: 0, results: [], next: null, previous: null },
                '/api/projects/:team/ai_observability/offline_experiments/': {
                    count: 0,
                    results: [],
                    next_cursor: null,
                },
                '/api/projects/:team/llm_analytics/score_definitions/': {
                    count: 0,
                    results: [],
                    next: null,
                    previous: null,
                },
            },
        }),
    ],
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await canvas.findByText('Build test cases for your agents')
        sceneLogic.actions.setScene(Scene.AIObservabilityOfflineExperiments, undefined, {
            params: {},
            searchParams: { tab: 'datasets' },
            hashParams: {},
        })
        await canvas.findByText('Manage datasets, follow score trends, and inspect offline experiment results.')
        fireEvent.click(canvas.getByRole('button', { name: 'Experiments' }))
        await canvas.findByText('Test agent changes before they reach production')
        await canvas.findByText('Manage datasets, follow score trends, and inspect offline experiment results.')
        fireEvent.click(canvas.getByRole('button', { name: 'Datasets' }))
        await canvas.findByText('Build test cases for your agents')
        sceneLogic.actions.setScene(Scene.AIObservabilityOfflineExperiments, undefined, {
            params: {},
            searchParams: { tab: 'datasets' },
            hashParams: {},
        })
        await canvas.findByText('Manage datasets, follow score trends, and inspect offline experiment results.')
    },
}

export const EmptyExperiments: Story = {
    render: () => <OfflineExperimentsScene />,
    parameters: {
        pageUrl: urls.aiObservabilityOfflineEvaluations(),
        mockDate: '2026-10-01',
        testOptions: { waitForSelector: '[data-attr="offline-experiments-get-started"]' },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team/ai_observability/offline_experiments/': {
                    count: 0,
                    results: [],
                    next_cursor: null,
                },
                '/api/projects/:team/datasets/': { count: 0, results: [], next: null, previous: null },
                '/api/projects/:team/llm_analytics/score_definitions/': {
                    count: 0,
                    results: [],
                    next: null,
                    previous: null,
                },
            },
        }),
    ],
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await canvas.findByText('Test agent changes before they reach production')
        await canvas.findByText('Manage datasets, follow score trends, and inspect offline experiment results.')
        fireEvent.click(canvas.getByRole('radio', { name: 'Revised prompt GPT' }))
        const result = within(await canvas.findByRole('region', { name: 'Revised prompt GPT result' }))
        result.getByText('Accuracy: 1')
        result.getByText('Helpfulness: 0.9')
    },
}

export const EmptyExperimentsNarrow: Story = {
    ...EmptyExperiments,
    parameters: { ...EmptyExperiments.parameters, narrow: true },
}

export const EmptyDatasetsNarrow: Story = {
    ...EmptyDatasets,
    parameters: { ...EmptyDatasets.parameters, narrow: true },
}
