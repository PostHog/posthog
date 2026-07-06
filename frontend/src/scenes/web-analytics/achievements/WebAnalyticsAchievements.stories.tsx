import { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { HttpResponse } from 'msw'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import type {
    AchievementProgressApi,
    AchievementsListResponseApi,
} from 'products/web_analytics/frontend/generated/api.schemas'

import { webAnalyticsAchievementsLogic } from './webAnalyticsAchievementsLogic'
import { WebAnalyticsAchievementsModal } from './WebAnalyticsAchievementsModal'

const STREAK_STAGE_NAMES = ['Getting started', 'Warming up', 'On a roll', 'Committed', 'Locked in']

const stages = (names: string[], thresholds: number[]): { stage: number; name: string; threshold: number }[] =>
    names.map((name, index) => ({ stage: index + 1, name, threshold: thresholds[index] }))

const unlockDates = (count: number): Record<string, string> => {
    const map: Record<string, string> = {}
    for (let stage = 1; stage <= count; stage++) {
        map[String(stage)] = `2026-06-${String(9 + stage).padStart(2, '0')}T00:00:00Z`
    }
    return map
}

const progress = (
    track_key: string,
    current_stage: number,
    progress_value: number,
    last_computed_at: string | null
): AchievementProgressApi => ({
    track_key,
    current_stage,
    progress_value,
    last_computed_at,
    unlocked_at: unlockDates(current_stage),
})

function buildOverview(streakThresholds: number[]): AchievementsListResponseApi {
    return {
        definitions: [
            {
                key: 'streak',
                display_name: 'Streak',
                description: 'Check your analytics regularly to keep a streak going.',
                scope: 'user',
                is_experiment_track: true,
                stages: stages(STREAK_STAGE_NAMES, streakThresholds),
            },
            {
                key: 'loyalty',
                display_name: 'Loyalty',
                description: 'Keep coming back — every visit counts.',
                scope: 'user',
                is_experiment_track: false,
                stages: stages(['Regular', 'Familiar', 'Devoted', 'Dedicated', 'Loyal'], [5, 15, 30, 60, 100]),
            },
            {
                key: 'explorer',
                display_name: 'Explorer',
                description: 'Dig into your data.',
                scope: 'user',
                is_experiment_track: false,
                stages: stages(['Curious', 'Digging in', 'Analyst', 'Power user', 'Data pro'], [1, 15, 40, 100, 250]),
            },
            {
                key: 'detective',
                display_name: 'Detective',
                description: 'Watch recordings to see what really happened.',
                scope: 'user',
                is_experiment_track: false,
                stages: stages(['First watch', 'Investigating', 'Sleuth', 'Profiler', 'Expert'], [1, 10, 50, 150, 500]),
            },
            {
                key: 'conversions',
                display_name: 'Conversions',
                description: 'Turn traffic into conversions.',
                scope: 'team',
                is_experiment_track: false,
                stages: stages(
                    ['First conversion', 'On target', 'Optimizing', 'Converting', 'Conversion pro'],
                    [1, 3, 5, 100, 1000]
                ),
            },
            {
                key: 'traffic',
                display_name: 'Traffic',
                description: 'Watch your pageviews climb.',
                scope: 'team',
                is_experiment_track: false,
                stages: stages(
                    ['On the board', 'Picking up', 'Major traffic', 'High volume', 'Viral'],
                    [10000, 100000, 1000000, 10000000, 100000000]
                ),
            },
        ],
        user_progress: [
            progress('streak', 2, streakThresholds[2] - 1, '2026-06-16T00:00:00Z'),
            progress('loyalty', 1, 9, '2026-06-16T00:00:00Z'),
            progress('explorer', 3, 62, '2026-06-16T00:00:00Z'),
            progress('detective', 0, 0, null),
        ],
        team_progress: [
            progress('conversions', 2, 4, '2026-06-16T00:00:00Z'),
            progress('traffic', 2, 250000, '2026-06-16T00:00:00Z'),
        ],
        pending_celebrations: [],
    }
}

function buildTierShowcase(): AchievementsListResponseApi {
    const base = buildOverview([2, 4, 7, 14, 30])
    return {
        ...base,
        user_progress: [
            progress('streak', 1, 3, '2026-06-16T00:00:00Z'),
            progress('loyalty', 2, 20, '2026-06-16T00:00:00Z'),
            progress('explorer', 3, 60, '2026-06-16T00:00:00Z'),
            progress('detective', 4, 200, '2026-06-16T00:00:00Z'),
        ],
        team_progress: [progress('traffic', 5, 200000000, '2026-06-16T00:00:00Z'), progress('conversions', 0, 0, null)],
    }
}

const overviewDecorator = (streakThresholds: number[]): ReturnType<typeof mswDecorator> =>
    mswDecorator({
        get: {
            '/api/projects/:team_id/web_analytics_achievements/overview/': () =>
                HttpResponse.json(buildOverview(streakThresholds)),
        },
    })

function OpenAchievementsModal({ expandTrack }: { expandTrack?: string }): JSX.Element {
    const { openModal, toggleTrackExpanded } = useActions(webAnalyticsAchievementsLogic)
    useEffect(() => {
        openModal()
        if (expandTrack) {
            toggleTrackExpanded(expandTrack)
        }
    }, [openModal, toggleTrackExpanded, expandTrack])
    return <WebAnalyticsAchievementsModal />
}

const meta: Meta = {
    title: 'Scenes-App/Web Analytics/Achievements',
    component: WebAnalyticsAchievementsModal,
    parameters: {
        layout: 'fullscreen',
        testOptions: { waitForSelector: '[data-attr="web-analytics-achievement-streak"]' },
    },
}
export default meta

type Story = StoryObj<typeof WebAnalyticsAchievementsModal>

export const HybridArm: Story = {
    decorators: [overviewDecorator([2, 4, 7, 14, 30])],
    parameters: {
        featureFlags: {
            [FEATURE_FLAGS.WEB_ANALYTICS_ACHIEVEMENTS]: true,
            [FEATURE_FLAGS.WEB_ANALYTICS_STREAK_CADENCE]: 'hybrid',
        },
    },
    render: () => <OpenAchievementsModal />,
}

export const DailyOnlyArm: Story = {
    decorators: [overviewDecorator([2, 4, 7, 14, 30])],
    parameters: {
        featureFlags: {
            [FEATURE_FLAGS.WEB_ANALYTICS_ACHIEVEMENTS]: true,
            [FEATURE_FLAGS.WEB_ANALYTICS_STREAK_CADENCE]: 'daily-only',
        },
    },
    render: () => <OpenAchievementsModal />,
}

export const WeeklyOnlyArm: Story = {
    decorators: [overviewDecorator([2, 3, 4, 8, 12])],
    parameters: {
        featureFlags: {
            [FEATURE_FLAGS.WEB_ANALYTICS_ACHIEVEMENTS]: true,
            [FEATURE_FLAGS.WEB_ANALYTICS_STREAK_CADENCE]: 'weekly-only',
        },
    },
    render: () => <OpenAchievementsModal />,
}

export const TierColors: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/web_analytics_achievements/overview/': () =>
                    HttpResponse.json(buildTierShowcase()),
            },
        }),
    ],
    parameters: {
        featureFlags: {
            [FEATURE_FLAGS.WEB_ANALYTICS_ACHIEVEMENTS]: true,
            [FEATURE_FLAGS.WEB_ANALYTICS_STREAK_CADENCE]: 'hybrid',
        },
    },
    render: () => <OpenAchievementsModal />,
}

export const ExpandedLadder: Story = {
    decorators: [overviewDecorator([2, 4, 7, 14, 30])],
    parameters: {
        featureFlags: {
            [FEATURE_FLAGS.WEB_ANALYTICS_ACHIEVEMENTS]: true,
            [FEATURE_FLAGS.WEB_ANALYTICS_STREAK_CADENCE]: 'hybrid',
        },
    },
    render: () => <OpenAchievementsModal expandTrack="explorer" />,
}
