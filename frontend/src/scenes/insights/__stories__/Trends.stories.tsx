import { Meta } from '@storybook/react'

import { keaStory } from 'lib/storybook/kea-story'
import { rest } from 'msw'
import { worker } from '~/mocks/browser'
import { Insights } from '../Insights'

import trendsJson from './trends.json'

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
    return keaStory(Insights, trendsJson)()
}
