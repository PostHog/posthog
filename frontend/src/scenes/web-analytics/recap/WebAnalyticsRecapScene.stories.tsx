import { Meta } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { WebAnalyticsRecapResponseApi, WoWChangeApi } from 'products/web_analytics/frontend/generated/api.schemas'

const up = (percent: number): WoWChangeApi => ({
    percent,
    direction: 'Up',
    color: '#2f7d4f',
    text: `Up ${percent}%`,
    long_text: `Up ${percent}% from previous week`,
})

const recapMock: WebAnalyticsRecapResponseApi = {
    visitors: { current: 12402, previous: 10510, change: up(18) },
    pageviews: { current: 38211, previous: 33100, change: up(15) },
    sessions: { current: 15890, previous: 14002, change: up(13) },
    bounce_rate: { current: 41, previous: 47, change: { ...up(13), direction: 'Down', text: 'Down 13%' } },
    avg_session_duration: { current: '2m 34s', previous: '2m 10s', change: up(11) },
    top_pages: [
        { host: '', path: '/pricing', visitors: 3201, change: up(42) },
        { host: '', path: '/', visitors: 2890, change: up(8) },
        { host: '', path: '/blog/launch-week', visitors: 1502, change: up(120) },
    ],
    top_sources: [
        { name: 'google.com', visitors: 5400, change: up(20) },
        { name: 'twitter.com', visitors: 1820, change: up(60) },
    ],
    goals: [{ name: 'Signed up', conversions: 312, change: up(25) }],
    dashboard_url: '/project/1/web',
    persona: {
        id: 'traffic_magnet',
        name: 'Traffic Magnet',
        emoji: '🧲',
        blurb: 'Visitors surged +18% this week. Whatever you’re doing, keep doing it.',
        color: '#e0a23b',
    },
    highlights: [
        {
            id: 'milestone',
            emoji: '🎉',
            title: 'Milestone unlocked',
            value: '10,000 visitors',
            detail: 'You crossed a new visitor milestone this week.',
        },
        {
            id: 'rising_page',
            emoji: '📈',
            title: 'Rising star page',
            value: '/blog/launch-week',
            detail: 'Up 120% in visitors week over week.',
        },
        {
            id: 'top_source',
            emoji: '🌐',
            title: 'Top source',
            value: 'google.com',
            detail: '5,400 visitors came from here.',
        },
    ],
    period_label: 'Last 7 days',
    period_start: '2023-01-25',
    period_end: '2023-02-01',
    project_name: 'PostHog App + Website',
    recap_url: '/project/1/web/recap?utm_source=web_analytics_recap',
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Web Analytics/Weekly Recap',
    // Animated scene (count-up + Hogfetti) — viewable in Storybook but excluded from visual snapshots.
    tags: ['test-skip'],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
        pageUrl: urls.webAnalyticsRecap(),
        featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_RECAP],
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/web_analytics/recap/': () => [200, recapMock],
            },
        }),
    ],
}
export default meta

export function WeeklyRecap(): JSX.Element {
    return <App />
}
