import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { ScoreDefinitionApi } from '../generated/api.schemas'
import { AIObservabilityScorerScene } from './AIObservabilityScorerScene'

const definition: ScoreDefinitionApi = {
    id: 'b4f331fe-7d3b-4bbe-9f88-52e1b0a8b000',
    name: 'Answer quality',
    description: 'How well the response answers the question, scored from 0 to 1.',
    kind: 'numeric',
    archived: false,
    current_version: 3,
    current_version_id: 'b4f331fe-7d3b-4bbe-9f88-52e1b0a8b003',
    config: { min: 0, max: 1, passing_rule: { operator: 'gte', threshold: 0.8 } },
    created_by: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-02T00:00:00Z',
    team: 997,
}

const meta: Meta<typeof AIObservabilityScorerScene> = {
    title: 'AI observability/Scorer editor',
    component: AIObservabilityScorerScene,
    args: { scorerId: definition.id },
    parameters: {
        pageUrl: urls.aiObservabilityScorer(definition.id),
        featureFlags: [FEATURE_FLAGS.AI_OBSERVABILITY_OFFLINE_EVALUATIONS],
    },
    decorators: [
        mswDecorator({
            get: { '/api/projects/:team/llm_analytics/score_definitions/:id/': definition },
            patch: {
                '/api/projects/:team/llm_analytics/score_definitions/:id/': async ({ request }) => ({
                    ...definition,
                    ...((await request.json()) as object),
                }),
            },
            post: {
                '/api/projects/:team/llm_analytics/score_definitions/': async ({ request }) => ({
                    ...definition,
                    ...((await request.json()) as object),
                    current_version: 1,
                }),
                '/api/projects/:team/llm_analytics/score_definitions/:id/new_version/': async ({ request }) => ({
                    ...definition,
                    ...((await request.json()) as object),
                    current_version: 4,
                }),
            },
        }),
    ],
}
export default meta
type Story = StoryObj<typeof AIObservabilityScorerScene>

export const Numeric: Story = {}
export const NewScorer: Story = {
    args: { scorerId: 'new' },
    parameters: { pageUrl: urls.aiObservabilityScorer('new') },
}
export const BooleanDetector: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team/llm_analytics/score_definitions/:id/': {
                    ...definition,
                    name: 'Hallucination detected',
                    description: 'Flags responses that contain unsupported claims.',
                    kind: 'boolean',
                    config: { true_is_failure: true, true_label: 'Detected', false_label: 'Not detected' },
                },
            },
        }),
    ],
}
export const LegacyBoolean: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team/llm_analytics/score_definitions/:id/': {
                    ...definition,
                    name: 'Review outcome',
                    kind: 'boolean',
                    config: { true_label: 'Yes', false_label: 'No' },
                },
            },
        }),
    ],
}
export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="w-[520px]">
                <Story />
            </div>
        ),
    ],
}
export const LoadError: Story = {
    decorators: [mswDecorator({ get: { '/api/projects/:team/llm_analytics/score_definitions/:id/': [500, {}] } })],
}
