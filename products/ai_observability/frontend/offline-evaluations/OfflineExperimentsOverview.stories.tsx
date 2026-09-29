import type { Meta, StoryObj } from '@storybook/react'
import { fireEvent, waitFor } from '@testing-library/react'

import { playHoverAtFraction } from '@posthog/quill-charts/story-helpers'

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
                '/api/projects/:team/ai_observability/offline_experiments/:id/scorer_summaries/': {
                    results: overviewScorers.map((scorer) => overviewHistory(scorer)[0].summary),
                    count: 3,
                    next_cursor: null,
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
export const PartialHistory: Story = {
    parameters: { pageUrl: `${urls.aiObservabilityOfflineEvaluations()}?scores=${overviewScorers[0].id}` },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team/ai_observability/offline_scorers/:id/history/': {
                    count: 200,
                    next_cursor: 'older-results',
                    results: overviewHistory(overviewScorers[0]),
                },
            },
        }),
    ],
}
export const SynchronizedHover: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team/ai_observability/offline_scorers/:id/history/': ({ params }) => {
                    const points = overviewHistory(overviewScorers.find((scorer) => scorer.id === params.id)!)
                    const results =
                        params.id === overviewScorers[1].id ? points.filter((_, index) => index % 2 === 0) : points
                    return { count: results.length, next_cursor: null, results }
                },
            },
        }),
    ],
    play: async ({ canvasElement }) => {
        const charts = await waitFor(() => {
            const elements = canvasElement.querySelectorAll<HTMLElement>('[data-attr="offline-score-trend"]')
            if (elements.length !== 3) {
                throw new Error('Score charts have not loaded')
            }
            return elements
        })
        const hover = async (chart: HTMLElement): Promise<void> => {
            const path = await waitFor(() => {
                const element = chart.querySelector<SVGPathElement>('[data-attr="offline-score-lines"] path')
                if (!element?.getAttribute('d')) {
                    throw new Error('Score chart has not finished rendering')
                }
                return element
            })
            const point = path.getPointAtLength(0)
            const rect = chart.getBoundingClientRect()
            await playHoverAtFraction(chart, point.x / rect.width, point.y / rect.height)
        }
        for (const chart of [charts[0], charts[2]]) {
            await hover(chart)
            await waitFor(() => {
                if (canvasElement.querySelectorAll('[data-attr="offline-score-crosshair"]').length !== 3) {
                    throw new Error('The hover guide must appear on every chart')
                }
                const fractions = Array.from(charts, (element) => {
                    const guide = element.querySelector('[data-attr="offline-score-crosshair"]')!
                    const plot = element.querySelector('[data-attr="offline-score-lines"] clipPath rect')!
                    return (
                        (Number(guide.getAttribute('x1')) - Number(plot.getAttribute('x'))) /
                        Number(plot.getAttribute('width'))
                    )
                })
                if (fractions.some((fraction) => Math.abs(fraction - fractions[0]) > 0.000001)) {
                    throw new Error('The hover guides must mark the same time, even with missing experiments')
                }
            })
            fireEvent.mouseLeave(chart)
            await waitFor(() => {
                if (canvasElement.querySelector('[data-attr="offline-score-crosshair"]')) {
                    throw new Error('The hover guides must clear when the pointer leaves')
                }
            })
        }
        await hover(charts[0])
    },
}
export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="@container/main-content w-[520px]">
                <Story />
            </div>
        ),
    ],
}
export const PartialHistoryNarrow: Story = {
    ...PartialHistory,
    decorators: [PartialHistory.decorators, Narrow.decorators].flat().filter((decorator) => !!decorator),
}
export const SynchronizedHoverNarrow: Story = {
    ...SynchronizedHover,
    decorators: [SynchronizedHover.decorators, Narrow.decorators].flat().filter((decorator) => !!decorator),
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

export const DefaultScorers: Story = {
    parameters: { pageUrl: `${urls.aiObservabilityOfflineEvaluations()}?scores=` },
}
export const MultipleVersions: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team/ai_observability/offline_scorers/:id/history/': ({ params }) => {
                    const points = overviewHistory(overviewScorers.find((scorer) => scorer.id === params.id)!)
                    const olderPoints = points.map((point) => ({
                        ...point,
                        summary: {
                            ...point.summary,
                            scorer: {
                                ...point.summary.scorer,
                                id: point.summary.scorer.id.replace('22222222', '44444444'),
                                version: 1,
                                config:
                                    point.summary.scorer.kind === 'numeric'
                                        ? { min: 0, max: 10 }
                                        : point.summary.scorer.config,
                            },
                        },
                    }))
                    return { count: points.length * 2, next_cursor: null, results: [...points, ...olderPoints] }
                },
            },
        }),
    ],
}
export const MultipleVersionsNarrow: Story = {
    decorators: [MultipleVersions.decorators, Narrow.decorators].flat().filter((decorator) => !!decorator),
}
