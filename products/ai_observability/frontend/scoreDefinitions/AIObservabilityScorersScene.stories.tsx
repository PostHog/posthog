import type { Meta, StoryObj } from '@storybook/react'
import { fireEvent, within } from '@testing-library/dom'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { ScoreDefinitionApi } from '../generated/api.schemas'
import { AIObservabilityScorersScene } from './AIObservabilityScorersScene'

const definition: ScoreDefinitionApi = {
    tags: ['production', 'quality', 'regression', 'support', 'long-tag-name-for-overflow'],
    id: 'b4f331fe-7d3b-4bbe-9f88-52e1b0a8b000',
    short_name: '',
    name: 'Answer quality',
    description: 'Quality of generated answers',
    kind: 'numeric',
    archived: false,
    current_version: 3,
    current_version_id: 'b4f331fe-7d3b-4bbe-9f88-52e1b0a8b003',
    config: { min: 0, max: 1 },
    created_by: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_by: null,
    updated_at: '2026-01-02T00:00:00Z',
    team: 997,
}

const meta: Meta<typeof AIObservabilityScorersScene> = {
    title: 'AI observability/Scorers',
    component: AIObservabilityScorersScene,
    parameters: {
        pageUrl: urls.aiObservabilityScorers(),
        mockDate: '2026-01-05',
        featureFlags: [FEATURE_FLAGS.AI_OBSERVABILITY_OFFLINE_EVALUATIONS],
    },
    decorators: [
        (Story, { parameters }) => (
            <div
                className={
                    parameters.narrow ? 'w-[520px] @container/main-content' : 'w-[1200px] @container/main-content'
                }
            >
                <Story />
            </div>
        ),
        mswDecorator({
            get: {
                '/api/projects/:team/tags': ({ request }) => {
                    const tags = ['production', 'quality', 'regression', 'support']
                    return new URL(request.url).searchParams.has('limit') ? { results: tags, next: null } : tags
                },
                '/api/projects/:team/llm_analytics/score_definitions/': {
                    results: [
                        definition,
                        {
                            ...definition,
                            id: 'b4f331fe-7d3b-4bbe-9f88-52e1b0a8b010',
                            name: 'Safety',
                            kind: 'boolean',
                            config: { true_label: 'Safe', false_label: 'Unsafe' },
                        },
                    ],
                    count: 2,
                    next: null,
                    previous: null,
                },
                '/api/projects/:team/llm_analytics/score_definitions/:id/': definition,
            },
        }),
    ],
}

export default meta
type Story = StoryObj<typeof AIObservabilityScorersScene>

export const Default: Story = {}
export const OfflineDisabled: Story = {
    parameters: { featureFlags: { [FEATURE_FLAGS.AI_OBSERVABILITY_OFFLINE_EVALUATIONS]: false } },
}
export const Narrow: Story = {
    parameters: { narrow: true },
}
export const Empty: Story = {
    parameters: { testOptions: { waitForSelector: '[data-attr="product-empty-state"]' } },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team/llm_analytics/score_definitions/': {
                    results: [],
                    count: 0,
                    next: null,
                    previous: null,
                },
            },
        }),
    ],
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await canvas.findByText('Define how you measure agent quality')
        fireEvent.click(canvas.getByRole('radio', { name: 'Manual review' }))
        const review = within(await canvas.findByRole('region', { name: 'Manual review example' }))
        review.getByText('Answer quality')
        review.getByText('Groundedness')
        review.getByText('Outcome')
    },
}

export const EmptyNarrow: Story = {
    ...Empty,
    parameters: { ...Empty.parameters, narrow: true },
}
