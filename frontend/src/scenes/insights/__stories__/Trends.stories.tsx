import { Meta } from '@storybook/react'
import { createMemoryHistory } from 'history'
import { Provider } from 'kea'

import { rest } from 'msw'
import React from 'react'
import { initKea } from '~/initKea'
import { worker } from '~/mocks/browser'
import { Insights } from '../Insights'

export default {
    title: 'PostHog/Scenes/Insights/Trends',
} as Meta

export const TrendsSmoothing = (): JSX.Element => {
    worker.use(
        rest.post('/api/insight/trends', (_, res, ctx) => {
            return res(
                ctx.json({
                    result: [
                        {
                            action: {
                                id: '$pageview',
                                type: 'events',
                                order: 0,
                                name: '$pageview',
                                custom_name: null,
                                math: null,
                                math_property: null,
                                properties: [],
                            },
                            label: '$pageview',
                            count: 181260.0,
                            data: [32944.0, 26552.0, 9385.0, 6905.0, 31078.0, 30918.0, 30434.0, 13044.0],
                            labels: [
                                '7-Oct-2021',
                                '8-Oct-2021',
                                '9-Oct-2021',
                                '10-Oct-2021',
                                '11-Oct-2021',
                                '12-Oct-2021',
                                '13-Oct-2021',
                                '14-Oct-2021',
                            ],
                            days: [
                                '2021-10-07',
                                '2021-10-08',
                                '2021-10-09',
                                '2021-10-10',
                                '2021-10-11',
                                '2021-10-12',
                                '2021-10-13',
                                '2021-10-14',
                            ],
                        },
                    ],
                    last_refresh: '2021-10-14T11:13:28.176410Z',
                    is_cached: true,
                    next: null,
                })
            )
        })
    )

    const history = createMemoryHistory({
        initialEntries: [
            `/insights?${new URLSearchParams({
                insight: 'TRENDS',
                properties: JSON.stringify([]),
                filter_test_accounts: 'false',
                events: JSON.stringify([
                    { id: '$pageview', name: '$pageview', type: 'events', order: 0 },
                    { id: '$pageview', name: '$pageview', type: 'events', order: 1 },
                    { id: '$pageview', name: '$pageview', type: 'events', order: 2 },
                ]),
                actions: JSON.stringify([]),
                display: 'FunnelViz',
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
    preflight: {
        is_clickhouse_enabled: true,
    },
    default_event_name: '$pageview',
    persisted_feature_flags: [],
}
