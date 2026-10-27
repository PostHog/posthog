import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'

/** One aggregated count per series, the shape a bold-number trends query returns. */
function counts(...values: number[]): { results: { aggregated_value: number }[] } {
    return { results: values.map((value) => ({ aggregated_value: value })) }
}

/** An invented generation, as the events query returns it, for the example next to the instructions. */
const SAMPLE_GENERATION = {
    uuid: '01900000-0000-7000-8000-000000000001',
    event: '$ai_generation',
    timestamp: '2026-10-19T10:00:00Z',
    properties: {
        $ai_trace_id: 'trace-example-1',
        $ai_model: 'gpt-4.1-mini',
        $ai_input: [{ role: 'user', content: 'How do I export my dashboard as a PDF?' }],
        $ai_output_choices: [{ role: 'assistant', content: 'Open the dashboard menu and choose Export, then PDF.' }],
    },
}

function scene(matchingGenerations: number): ReturnType<typeof mswDecorator> {
    const queryResponse = ({ params }: { params: Record<string, string> }): [number, unknown] => [
        200,
        params.kind === 'EventsQuery'
            ? { results: matchingGenerations ? [[SAMPLE_GENERATION]] : [], columns: ['*'] }
            : counts(matchingGenerations, Math.round(matchingGenerations / 3)),
    ]
    return mswDecorator({
        get: {
            '/api/projects/:team_id/evaluations/': toPaginatedResponse([]),
            '/api/projects/:team_id/evaluation_directories/': [],
            '/api/environments/:team_id/llm_analytics/provider_keys/': toPaginatedResponse([]),
            '/api/projects/:team_id/llm_analytics/provider_keys/': toPaginatedResponse([]),
            '/api/environments/:team_id/llm_analytics/evaluation_config/': { active_provider_key: null },
        },
        // The query client puts the query kind in the path.
        post: {
            '/api/environments/:team_id/query/:kind/': queryResponse,
            '/api/environments/:team_id/query/': queryResponse,
        },
    })
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/AI observability/New evaluation',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-10-20',
        pageUrl: urls.aiObservabilityEvaluation('new'),
        featureFlags: [FEATURE_FLAGS.AI_OBSERVABILITY_EVALUATIONS_OVERVIEW],
        testOptions: {
            waitForSelector: [
                '[data-attr="llma-evaluation-create-volume"]',
                '[data-attr="llma-evaluation-create-sample"] dl',
            ],
        },
    },
}
export default meta
type Story = StoryObj<{}>

export const FromScratch: Story = { decorators: [scene(1240)] }

export const FromTemplate: Story = {
    parameters: { pageUrl: `${urls.aiObservabilityEvaluation('new')}?template=helpfulness` },
    decorators: [scene(1240)],
}

export const NothingMatches: Story = {
    parameters: {
        pageUrl: `${urls.aiObservabilityEvaluation('new')}?template=helpfulness`,
        testOptions: { waitForSelector: '[data-attr="llma-evaluation-create-volume-none"]' },
    },
    decorators: [scene(0)],
}
