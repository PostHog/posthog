import { Meta } from '@storybook/react'
import { createMemoryHistory } from 'history'
import { Provider } from 'kea'

import { rest } from 'msw'
import React from 'react'
import { initKea } from '~/initKea'
import { worker } from '~/mocks/browser'
import { Insights } from '../Insights'

export default {
    title: 'PostHog/Scenes/Insights/Retention',
} as Meta

export const TrendsSmoothing = (): JSX.Element => {
    worker.use(
        rest.get('/api/projects/:projectId/insights/retention/', (_, res, ctx) => {
            return res(ctx.json(sampleRetentionResponse))
        })
    )

    const history = createMemoryHistory({
        initialEntries: [
            `/insights?${new URLSearchParams({
                insight: 'RETENTION',
                filter_test_accounts: 'false',
                target_event: JSON.stringify([{ id: '$pageview', name: '$pageview', type: 'events', order: 0 }]),
                returning_event: JSON.stringify([{ id: '$pageview', name: '$pageview', type: 'events', order: 0 }]),
                actions: JSON.stringify([]),
                interval: 'day',
                new_entity: JSON.stringify([]),
                date_from: '-14d',
                exclusions: JSON.stringify([]),
            })}#fromItem=`,
        ],
    })

    // @ts-ignore
    history.pushState = history.push
    // @ts-ignore
    history.replaceState = history.replace

    // This is data that is rendered into the html. I tried not to use this and just
    // use the endoints, but it appears to be difficult to set this up to not have
    // race conditions.
    // @ts-ignore
    window.POSTHOG_APP_CONTEXT = sampleContextData

    initKea({ routerHistory: history, routerLocation: history.location })

    return (
        <Provider>
            <Insights />
        </Provider>
    )
}

// This is data that is rendered into the html. I tried not to use this and just
// use the endoints, but it appears to be difficult to set this up to not have
// race conditions.
// NOTE: these are not complete according to type, but the minimum I could get away with
const sampleContextData = {
    current_team: {
        id: 2,
    },
    current_user: { organization: { available_features: ['correlation_analysis'] } },
    preflight: {
        is_clickhouse_enabled: true,
        instance_preferences: { disable_paid_fs: false },
    },
    default_event_name: '$pageview',
    persisted_feature_flags: ['correlation-analysis'],
}

const sampleRetentionResponse = {
    result: [
        {
            values: [
                { count: 1086, people: [] },
                { count: 13, people: [] },
                { count: 15, people: [] },
                { count: 12, people: [] },
                { count: 10, people: [] },
                { count: 5, people: [] },
                { count: 3, people: [] },
                { count: 5, people: [] },
                { count: 4, people: [] },
                { count: 3, people: [] },
                { count: 6, people: [] },
            ],
            label: 'Day 0',
            date: '2021-11-13T00:00:00Z',
        },
        {
            values: [
                { count: 819, people: [] },
                { count: 21, people: [] },
                { count: 13, people: [] },
                { count: 13, people: [] },
                { count: 11, people: [] },
                { count: 6, people: [] },
                { count: 6, people: [] },
                { count: 4, people: [] },
                { count: 3, people: [] },
                { count: 3, people: [] },
            ],
            label: 'Day 1',
            date: '2021-11-14T00:00:00Z',
        },
        {
            values: [
                { count: 1245, people: [] },
                { count: 56, people: [] },
                { count: 37, people: [] },
                { count: 28, people: [] },
                { count: 8, people: [] },
                { count: 7, people: [] },
                { count: 7, people: [] },
                { count: 13, people: [] },
                { count: 6, people: [] },
            ],
            label: 'Day 2',
            date: '2021-11-15T00:00:00Z',
        },
        {
            values: [
                { count: 1369, people: [] },
                { count: 67, people: [] },
                { count: 28, people: [] },
                { count: 30, people: [] },
                { count: 7, people: [] },
                { count: 7, people: [] },
                { count: 29, people: [] },
                { count: 10, people: [] },
            ],
            label: 'Day 3',
            date: '2021-11-16T00:00:00Z',
        },
        {
            values: [
                { count: 1559, people: [] },
                { count: 64, people: [] },
                { count: 37, people: [] },
                { count: 14, people: [] },
                { count: 12, people: [] },
                { count: 28, people: [] },
                { count: 14, people: [] },
            ],
            label: 'Day 4',
            date: '2021-11-17T00:00:00Z',
        },
        {
            values: [
                { count: 1912, people: [] },
                { count: 96, people: [] },
                { count: 26, people: [] },
                { count: 18, people: [] },
                { count: 34, people: [] },
                { count: 20, people: [] },
            ],
            label: 'Day 5',
            date: '2021-11-18T00:00:00Z',
        },
        {
            values: [
                { count: 1595, people: [] },
                { count: 49, people: [] },
                { count: 21, people: [] },
                { count: 56, people: [] },
                { count: 24, people: [] },
            ],
            label: 'Day 6',
            date: '2021-11-19T00:00:00Z',
        },
        {
            values: [
                { count: 1013, people: [] },
                { count: 21, people: [] },
                { count: 18, people: [] },
                { count: 12, people: [] },
            ],
            label: 'Day 7',
            date: '2021-11-20T00:00:00Z',
        },
        {
            values: [
                { count: 721, people: [] },
                { count: 33, people: [] },
                { count: 16, people: [] },
            ],
            label: 'Day 8',
            date: '2021-11-21T00:00:00Z',
        },
        {
            values: [
                { count: 1183, people: [] },
                { count: 36, people: [] },
            ],
            label: 'Day 9',
            date: '2021-11-22T00:00:00Z',
        },
        { values: [{ count: 810, people: [] }], label: 'Day 10', date: '2021-11-23T00:00:00Z' },
    ],
    last_refresh: '2021-11-23T13:45:29.314009Z',
    is_cached: true,
}
