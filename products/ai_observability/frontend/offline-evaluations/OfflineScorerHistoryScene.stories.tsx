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
                '/api/projects/:project/llm_analytics/score_definitions/:definition/': OFFLINE_STORY_DEFINITION,
                '/api/projects/:project/llm_analytics/score_definitions/:definition/versions/': {
                    results: [OFFLINE_STORY_VERSION],
                    next_cursor: null,
                    count: 1,
                },
                '/api/projects/:project/llm_analytics/score_definitions/:definition/versions/:version/':
                    OFFLINE_STORY_VERSION,
                '/api/projects/:project/ai_observability/offline_scorers/:definition/history/': {
                    results: [...OFFLINE_STORY_POINTS].reverse(),
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
