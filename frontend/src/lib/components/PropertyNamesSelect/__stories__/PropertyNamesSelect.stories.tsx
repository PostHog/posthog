import { mockGetPersonProperties } from 'lib/components/TaxonomicFilter/__stories__/TaxonomicFilter.stories'
import { keaStory } from 'lib/storybook/kea-story'
import React from 'react'
import { worker } from '~/mocks/browser'
import { PropertyNamesSelect } from '../PropertyNamesSelect'

export default {
    title: 'PostHog/Components/PropertyNamesSelect',
}

export const EmptyWithOptions = (): JSX.Element => {
    worker.use(
        mockGetPersonProperties((_, res, ctx) =>
            res(
                ctx.delay(1500),
                ctx.json([
                    { id: 1, name: 'Property A', count: 10 },
                    { id: 2, name: 'Property B', count: 20 },
                    { id: 3, name: 'Property C', count: 30 },

                    { id: 4, name: 'Property D', count: 40 },
                    { id: 5, name: 'Property E', count: 50 },
                    { id: 6, name: 'Property F', count: 60 },

                    { id: 7, name: 'Property G', count: 70 },
                    { id: 8, name: 'Property H', count: 80 },
                    { id: 9, name: 'Property I', count: 90 },
                ])
            )
        )
    )

    return keaStory(
        () => (
            <PropertyNamesSelect
                onChange={(selectedProperties) => console.log('Selected Properties', selectedProperties)}
            />
        ),
        {
            kea: {
                router: {
                    location: {
                        pathname: '/insights',
                        search: '?insight=FUNNELS&properties=%5B%5D&filter_test_accounts=false&events=%5B%7B%22id%22%3A%22%24pageview%22%2C%22name%22%3A%22%24pageview%22%2C%22type%22%3A%22events%22%2C%22order%22%3A0%7D%2C%7B%22id%22%3A%22%24pageview%22%2C%22name%22%3A%22%24pageview%22%2C%22type%22%3A%22events%22%2C%22order%22%3A1%7D%2C%7B%22id%22%3A%22%24pageview%22%2C%22name%22%3A%22%24pageview%22%2C%22type%22%3A%22events%22%2C%22order%22%3A2%7D%5D&actions=%5B%5D&funnel_viz_type=steps&display=FunnelViz&interval=day&new_entity=%5B%5D&date_from=-14d',
                        hash: '',
                    },
                    searchParams: {
                        insight: 'FUNNELS',
                        properties: [],
                        filter_test_accounts: false,
                        events: [
                            {
                                id: '$pageview',
                                name: '$pageview',
                                type: 'events',
                                order: 0,
                            },
                            {
                                id: '$pageview',
                                name: '$pageview',
                                type: 'events',
                                order: 1,
                            },
                            {
                                id: '$pageview',
                                name: '$pageview',
                                type: 'events',
                                order: 2,
                            },
                        ],
                        actions: [],
                        funnel_viz_type: 'steps',
                        display: 'FunnelViz',
                        interval: 'day',
                        new_entity: [],
                        date_from: '-14d',
                    },
                    hashParams: {},
                },
            },
        }
    )()
}

export const RequestFailure = (): JSX.Element => {
    worker.use(mockGetPersonProperties((_, res, ctx) => res(ctx.delay(1500), ctx.status(500))))

    return (
        <PropertyNamesSelect
            onChange={(selectedProperties) => console.log('Selected Properties', selectedProperties)}
        />
    )
}
