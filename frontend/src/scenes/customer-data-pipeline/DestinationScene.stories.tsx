import { Meta, Story } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'
import { mswDecorator } from '~/mocks/browser'
import { useAvailableFeatures } from '~/mocks/features'
import { AvailableFeature } from '~/types'
import { Destination, DestinationData } from './Destinations'

const destinations: Destination[] = [
    {
        id: '1',
        name: 'My Amplitude Destination',
        description: 'My Amplitude Destination',
        type: 'amplitude',
        mappings: [],
        config: {
            api_key: '123',
        },
        stats: {
            events_sent_last_24_hours: 1234,
            failures_last_24_hours: 5432,
            successes_last_24_hours: 51,
        },
        created_at: '2021-01-01T00:00:00.000Z',
        updated_at: '2021-01-01T00:00:00.000Z',
    },
    {
        id: '2',
        name: 'My Mixpanel Destination',
        description: 'My Mixpanel Destination',
        type: 'mixpanel',
        mappings: [],
        config: {
            api_secret: '123',
        },
        stats: {
            events_sent_last_24_hours: 15,
            failures_last_24_hours: 5,
            successes_last_24_hours: 2,
        },
        created_at: '2021-01-01T00:00:00.000Z',
        updated_at: '2021-01-01T00:00:00.000Z',
    },
]

const destinationsLookup = Object.fromEntries(destinations.map((destination) => [destination.id, destination]))

export default {
    title: 'Scenes-App/Customer Data Pipeline',
    parameters: {
        layout: 'fullscreen',
        options: { showPanel: false },
        testOptions: {
            excludeNavigationFromSnapshot: true,
        },
        viewMode: 'story',
    },

    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/destinations/': (req, res, ctx) => {
                    return res(ctx.delay(1000), ctx.json({ destinations }))
                },
                '/api/projects/:team_id/destinations/:destination_id': (req, res, ctx) => {
                    return res(ctx.delay(1000), ctx.json(destinationsLookup[req.params.destination_id as string]))
                },
            },
            post: {
                '/api/projects/:team_id/destinations/': (req, res, ctx) => {
                    const destination = req.body as DestinationData
                    // Randomly assign an ID, fill in created_at and updated_at
                    // fields and push it to the list of destinations.
                    destinations.push({
                        ...destination,
                        id: Math.random().toString(),
                        created_at: new Date().toISOString(),
                        updated_at: new Date().toISOString(),
                        stats: {
                            events_sent_last_24_hours: 0,
                            failures_last_24_hours: 0,
                            successes_last_24_hours: 0,
                        },
                    })
                    return res(ctx.delay(1000), ctx.json({}))
                },
            },
        }),
    ],
} as Meta

export const DestinationTypeScene: Story = () => {
    useAvailableFeatures([AvailableFeature.APP_METRICS])
    useEffect(() => {
        router.actions.push(urls.destinationTypes())
    })
    return <App />
}

export const CreateDestinationOfTypeScene: Story = () => {
    useAvailableFeatures([AvailableFeature.APP_METRICS])
    useEffect(() => {
        router.actions.push(urls.createDestinationOfType('amplitude'))
    })
    return <App />
}

export const DestinationsListScene: Story = () => {
    useAvailableFeatures([AvailableFeature.APP_METRICS])
    useEffect(() => {
        router.actions.push(urls.destinations())
    })
    return <App />
}
