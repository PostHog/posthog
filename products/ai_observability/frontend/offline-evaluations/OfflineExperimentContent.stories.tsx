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

export const DetailedResult: Story = {
    parameters: {
        pageUrl: `${urls.aiObservabilityOfflineEvaluationExperiment(detailExperiment.id)}?item_id=${detailItems[0].id}&result_id=${offlineDetailItemResults(detailItems[0].id)[0].id}&scorer_version_id=${detailSummaries[0].scorer.id}`,
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team/ai_observability/offline_experiments/:id/items/:itemId/payload/': ({
                    params,
                }) => ({
                    id: params.itemId,
                    payload_state: 'available',
                    payload_expires_at: null,
                    available: true,
                    data: {
                        input: {
                            question: 'Explain how to compare two versions of a support assistant.',
                            requirements: [
                                'Use the same test cases',
                                'Consider quality and response time',
                                'Explain errors',
                            ],
                            context: { dataset: 'example-support-questions', trials: 3 },
                        },
                        output: 'Run both assistant versions against the same set of questions. Keep the dataset, scorer configuration, and number of trials the same so each result has a comparable baseline.\n\nCompare answer quality and response time separately. A faster answer is useful only if it still answers the question accurately. Review individual cases where the scores differ to understand which responses improved and which became less reliable.\n\nCheck evaluator errors and missing results before interpreting averages. A run with missing scores may look better because difficult cases were left out. Use repeated trials to see whether improvements are consistent, then inspect the original input, output, and evaluator reasoning for any surprising result.\n\n'.repeat(
                            3
                        ),
                        expected_output:
                            'Use identical test cases and scorer versions for both assistants. Compare quality and latency, review cases with different scores, and check errors or missing results before drawing conclusions. Repeat trials to assess consistency.',
                        metadata: {
                            dataset: 'example-support-questions',
                            tags: ['comparison', 'regression'],
                            trial: 1,
                        },
                    },
                }),
                '/api/projects/:team/ai_observability/offline_experiments/:id/results/:resultId/payload/': ({
                    params,
                }) => ({
                    id: params.resultId,
                    payload_state: 'available',
                    payload_expires_at: null,
                    available: true,
                    data: {
                        reasoning:
                            'The response covers the key comparison criteria: a shared dataset, consistent scorer versions, separate quality and latency measurements, and repeated trials.\n\nIt also explains why missing results and evaluator errors can distort averages. The recommendation to inspect individual cases makes the comparison actionable. It could be more precise about how to summarize variation across trials, so the response receives partial credit for that criterion.',
                        metadata: {
                            rubric: ['comparability', 'coverage', 'clarity'],
                            evaluator: { version: 'example-v2' },
                        },
                    },
                }),
            },
        }),
    ],
}
