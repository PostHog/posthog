import type { Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'
import { BindLogic } from 'kea'
import { combineUrl } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { DatasetItemReadApi, DatasetReadApi } from '../generated/api.schemas'
import { aiObservabilityDatasetLogic } from './aiObservabilityDatasetLogic'
import { AIObservabilityDatasetScene } from './AIObservabilityDatasetScene'

const dataset: DatasetReadApi = {
    id: 'example-dataset',
    name: 'Answer quality',
    description: 'Questions and expected answers for evaluating the support assistant.',
    metadata: { owner: 'support', language: 'en' },
    tags: [],
    archived: false,
    current_revision: 1,
    current_revision_id: 'example-revision',
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    created_by: null,
    team_id: 997,
    user_access_level: 'editor',
}

const item: DatasetItemReadApi = {
    id: 'example-item',
    dataset: dataset.id,
    client_item_id: null,
    version: 1,
    version_id: 'example-item-version',
    dataset_revision: 1,
    dataset_revision_id: 'example-revision',
    archived: false,
    input: { question: 'How do I reset my password?' },
    expected_output: { answer: 'Use the password reset link on the sign-in page.' },
    source_output: null,
    metadata: { category: 'account' },
    source_trace_id: null,
    source_timestamp: null,
    source_event_id: null,
    created_by: null,
    created_at: dataset.created_at,
    updated_at: dataset.created_at,
    version_created_at: dataset.created_at,
    version_created_by: null,
    team_id: 997,
}

const meta: Meta<typeof AIObservabilityDatasetScene> = {
    title: 'Scenes-App/AI observability/Dataset',
    component: AIObservabilityDatasetScene,
    parameters: {
        mockDate: '2024-01-02T12:00:00Z',
        pageUrl: urls.aiObservabilityDataset(dataset.id),
        featureFlags: [FEATURE_FLAGS.LLM_ANALYTICS_DATASETS, FEATURE_FLAGS.AI_OBSERVABILITY_OFFLINE_EVALUATIONS],
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team/datasets/:id/': dataset,
                '/api/projects/:team/datasets/:id/revisions/': { count: 0, results: [], next: null, previous: null },
                '/api/projects/:team/dataset_items/': { count: 1, results: [item], next: null, previous: null },
            },
        }),
        (Story, { parameters }) => (
            <BindLogic logic={aiObservabilityDatasetLogic} props={{ datasetId: parameters.datasetId || dataset.id }}>
                <Story />
            </BindLogic>
        ),
    ],
    play: async ({ canvasElement }) => {
        await within(canvasElement).findByText(item.id)
    },
}
export default meta
type Story = StoryObj<typeof AIObservabilityDatasetScene>

export const Items: Story = {}
export const Details: Story = {
    parameters: { pageUrl: combineUrl(urls.aiObservabilityDataset(dataset.id), { tab: 'metadata' }).url },
}
export const NewDataset: Story = {
    parameters: { datasetId: 'new', pageUrl: urls.aiObservabilityDataset('new') },
    play: async ({ canvasElement }) => {
        await waitFor(() => {
            if (!canvasElement.querySelector('.monaco-editor')) {
                throw new Error('Waiting for the dataset metadata editor')
            }
        })
    },
}
export const DatasetsOnlyNarrow: Story = {
    parameters: {
        featureFlags: {
            [FEATURE_FLAGS.LLM_ANALYTICS_DATASETS]: true,
            [FEATURE_FLAGS.AI_OBSERVABILITY_OFFLINE_EVALUATIONS]: false,
        },
    },
    decorators: [
        (Story) => (
            <div className="w-[520px]">
                <Story />
            </div>
        ),
    ],
}
export const ReadOnly: Story = {
    decorators: [
        mswDecorator({
            get: { '/api/projects/:team/datasets/:id/': { ...dataset, user_access_level: 'viewer' } },
        }),
    ],
}
