import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { OfflineExperimentsOverview } from './OfflineExperimentsOverview'
import { overviewExperiments, overviewHistory, overviewScorers } from './offlineOverviewFixtures'

const meta: Meta<typeof OfflineExperimentsOverview> = {
    title: 'Scenes-App/AI observability/Offline experiments/Overview',
    component: OfflineExperimentsOverview,
    args: { teamId: 997, userId: 997, timezone: 'UTC' },
    parameters: {
        mockDate: '2026-09-28T12:00:00Z',
        pageUrl: `${urls.aiObservabilityOfflineEvaluations()}?scores=${overviewScorers.map((scorer) => scorer.id).join(',')}`,
        featureFlags: [FEATURE_FLAGS.AI_OBSERVABILITY_OFFLINE_EVALUATIONS],
    },
    decorators: [
        (Story) => (
            <div className="@container/main-content">
                <Story />
            </div>
        ),
        mswDecorator({
            get: {
                '/api/projects/:team/ai_observability/offline_experiments/': {
                    count: 8,
                    next_cursor: null,
                    results: overviewExperiments,
                },
                '/api/projects/:team/llm_analytics/score_definitions/': { count: 3, results: overviewScorers },
                '/api/projects/:team/llm_analytics/score_definitions/:id/': ({ params }) =>
                    overviewScorers.find((scorer) => scorer.id === params.id),
                '/api/projects/:team/ai_observability/offline_scorers/:id/history/': ({ params }) => ({
                    count: 6,
                    next_cursor: null,
                    results: overviewHistory(overviewScorers.find((scorer) => scorer.id === params.id)!),
                }),
            },
        }),
    ],
}
export default meta
type Story = StoryObj<typeof OfflineExperimentsOverview>

export const RecentExperiments: Story = {}
export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="@container/main-content w-[520px]">
                <Story />
            </div>
        ),
    ],
}
export const FilteredTrends: Story = {
    ...Narrow,
    parameters: {
        pageUrl: `${urls.aiObservabilityOfflineEvaluations()}?scores=${overviewScorers[0].id}&date_from=-7d&run_source=ci&statuses=completed`,
    },
}
export const Empty: Story = {
    parameters: { pageUrl: `${urls.aiObservabilityOfflineEvaluations()}?scores=` },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team/ai_observability/offline_experiments/': {
                    count: 0,
                    next_cursor: null,
                    results: [],
                },
            },
        }),
    ],
}
export const EmptyNarrow: Story = {
    ...Empty,
    decorators: [Empty.decorators, Narrow.decorators].flat().filter((decorator) => !!decorator),
}
export const NoMatchingExperiments: Story = {
    parameters: { pageUrl: `${urls.aiObservabilityOfflineEvaluations()}?scores=&run_source=local` },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team/ai_observability/offline_experiments/': ({ request }) =>
                    new URL(request.url).searchParams.get('run_source')
                        ? { count: 0, next_cursor: null, results: [] }
                        : { count: 8, next_cursor: null, results: overviewExperiments },
            },
        }),
    ],
}
export const ListError: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team/ai_observability/offline_experiments/': () => [403, { detail: 'Unavailable' }],
            },
        }),
    ],
}
export const ScoreError: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team/ai_observability/offline_scorers/:id/history/': () => [
                    403,
                    { detail: 'Unavailable' },
                ],
            },
        }),
    ],
}
