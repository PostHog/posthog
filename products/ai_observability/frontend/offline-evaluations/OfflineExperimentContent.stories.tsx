import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import {
    detailExperiment,
    detailItems,
    detailSummaries,
    makeOfflineDetailCells,
    offlineDetailItemResults,
} from './offlineDetailFixtures'
import { OfflineExperimentContent } from './OfflineExperimentContent'

const meta: Meta<typeof OfflineExperimentContent> = {
    title: 'Scenes-App/AI observability/Offline experiments/Experiment',
    component: OfflineExperimentContent,
    args: { teamId: 997, experimentId: detailExperiment.id },
    parameters: {
        mockDate: '2026-09-28T12:00:00Z',
        pageUrl: urls.aiObservabilityOfflineEvaluationExperiment(detailExperiment.id),
        featureFlags: [FEATURE_FLAGS.AI_OBSERVABILITY_OFFLINE_EVALUATIONS],
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team/ai_observability/offline_experiments/:id/': detailExperiment,
                '/api/projects/:team/ai_observability/offline_experiments/:id/scorer_summaries/': {
                    count: detailSummaries.length,
                    next_cursor: null,
                    results: detailSummaries,
                },
                '/api/projects/:team/ai_observability/offline_experiments/:id/items/': {
                    count: detailItems.length,
                    next_cursor: null,
                    results: detailItems,
                    scorer_versions: [],
                },
                '/api/projects/:team/ai_observability/offline_experiments/:id/result_cells/': ({ request }) => {
                    const params = new URL(request.url).searchParams
                    return makeOfflineDetailCells(
                        params.get('item_ids')!.split(','),
                        params.get('scorer_version_ids')!.split(',')
                    )
                },
                '/api/projects/:team/ai_observability/offline_experiments/:id/items/:itemId/': ({ params }) =>
                    detailItems.find((item) => item.id === params.itemId),
                '/api/projects/:team/ai_observability/offline_experiments/:id/items/:itemId/payload/': ({
                    params,
                }) => ({
                    id: params.itemId,
                    payload_state: 'available',
                    payload_expires_at: null,
                    available: true,
                    data: {
                        input: { question: 'What is two plus two?' },
                        output: 'Four.',
                        expected_output: null,
                        metadata: { trial: 1 },
                    },
                }),
                '/api/projects/:team/ai_observability/offline_experiments/:id/items/:itemId/results/': ({
                    params,
                    request,
                }) => {
                    const version = new URL(request.url).searchParams.get('scorer_version_ids')
                    const results = offlineDetailItemResults(String(params.itemId)).filter(
                        (result) => !version || result.scorer.id === version
                    )
                    return { count: results.length, next_cursor: null, results }
                },
                '/api/projects/:team/ai_observability/offline_experiments/:id/results/:resultId/payload/': ({
                    params,
                }) => ({
                    id: params.resultId,
                    payload_state: 'available',
                    payload_expires_at: null,
                    available: true,
                    data: String(params.resultId).endsWith('000000003001')
                        ? { error_message: 'The evaluator did not finish in time.', metadata: {} }
                        : { reasoning: 'The response gives the expected numerical answer.', metadata: {} },
                }),
            },
        }),
    ],
}
export default meta
type Story = StoryObj<typeof OfflineExperimentContent>

export const AllScorers: Story = {}
export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="w-[520px]">
                <Story />
            </div>
        ),
    ],
}
export const ItemInspector: Story = {
    parameters: {
        pageUrl: `${urls.aiObservabilityOfflineEvaluationExperiment(detailExperiment.id)}?item_id=${detailItems[0].id}`,
    },
}
export const ExpiredPayload: Story = {
    ...ItemInspector,
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team/ai_observability/offline_experiments/:id/items/:itemId/payload/': ({
                    params,
                }) => ({
                    id: params.itemId,
                    payload_state: 'expired',
                    payload_expires_at: '2026-09-01T12:00:00Z',
                    available: false,
                    data: null,
                }),
            },
        }),
    ],
}
export const RequestFailure: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team/ai_observability/offline_experiments/:id/scorer_summaries/': () => [
                    403,
                    { detail: 'Scorer data is unavailable.' },
                ],
            },
        }),
    ],
}
