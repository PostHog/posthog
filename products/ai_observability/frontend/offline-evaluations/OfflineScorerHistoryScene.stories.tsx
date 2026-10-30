import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { OfflineScorerHistoryScene } from './OfflineScorerHistoryScene'
import { OFFLINE_STORY_DEFINITION, OFFLINE_STORY_POINTS, OFFLINE_STORY_VERSION } from './offlineScoreTrends.fixtures'

const meta: Meta<typeof OfflineScorerHistoryScene> = {
    title: 'AI observability/Offline experiments/Scorer history',
    component: OfflineScorerHistoryScene,
    args: { scorerId: OFFLINE_STORY_DEFINITION.id },
    parameters: {
        mockDate: '2026-01-20',
        pageUrl: urls.aiObservabilityOfflineScorerHistory(OFFLINE_STORY_DEFINITION.id),
        featureFlags: [FEATURE_FLAGS.AI_OBSERVABILITY_OFFLINE_EVALUATIONS],
        layout: 'padded',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team/tags': ({ request }) => {
                    const tags = ['quality', 'production', 'regression', 'support']
                    return new URL(request.url).searchParams.has('limit') ? { results: tags, next: null } : tags
                },
                '/api/projects/:project/llm_analytics/score_definitions/:definition/': OFFLINE_STORY_DEFINITION,
                '/api/projects/:project/llm_analytics/score_definitions/:definition/versions/': {
                    results: [OFFLINE_STORY_VERSION],
                    next_cursor: null,
                    count: 1,
                },
                '/api/projects/:project/llm_analytics/score_definitions/:definition/versions/:version/':
                    OFFLINE_STORY_VERSION,
                '/api/projects/:project/ai_observability/offline_scorers/:definition/history/': {
                    results: [...OFFLINE_STORY_POINTS].reverse().map((point, index) => ({
                        ...point,
                        experiment: {
                            ...point.experiment,
                            tags: index % 2 ? ['quality'] : ['quality', 'production', 'regression', 'support'],
                        },
                    })),
                    next_cursor: 'older-page',
                    count: 127,
                },
            },
        }),
    ],
}
export default meta
type Story = StoryObj<typeof OfflineScorerHistoryScene>
export const Default: Story = {}
export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="w-[520px]">
                <Story />
            </div>
        ),
    ],
}
export const EmptyHistory: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:project/ai_observability/offline_scorers/:definition/history/': {
                    results: [],
                    next_cursor: null,
                    count: 0,
                },
            },
        }),
    ],
}

export const ModelBreakdown: Story = {
    parameters: {
        pageUrl: `${urls.aiObservabilityOfflineScorerHistory(OFFLINE_STORY_DEFINITION.id)}?breakdown=model_version`,
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:project/ai_observability/offline_scorers/:definition/history/': ({ request }) => {
                    const breakdown = new URL(request.url).searchParams.get('breakdown')
                    const results =
                        breakdown === 'model_version'
                            ? OFFLINE_STORY_POINTS.flatMap((point) => [
                                  { ...point, breakdown_value: 'model-a' },
                                  {
                                      ...point,
                                      breakdown_value: 'model-b',
                                      summary: { ...point.summary, mean: (point.summary.mean ?? 0) / 2 },
                                  },
                              ])
                            : OFFLINE_STORY_POINTS.map((point) => ({
                                  ...point,
                                  breakdown_value:
                                      breakdown === 'suite_key'
                                          ? point.experiment.suite_key
                                          : breakdown === 'run_source'
                                            ? point.experiment.run_source
                                            : breakdown === 'prompt_version'
                                              ? point.experiment.prompt_version
                                              : breakdown === 'application_version'
                                                ? point.experiment.application_version
                                                : null,
                              }))
                    return { results, count: results.length, next_cursor: null }
                },
            },
        }),
    ],
}
