import { Meta, Story } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'
import { mswDecorator } from '~/mocks/browser'
import { useAvailableFeatures } from '~/mocks/features'
import { AvailableFeature } from '~/types'
import { DestinationType } from './DestinationTypes'
import { Destination } from './Destinations'

const destinationTypes: DestinationType[] = [
    {
        id: 'amplitude',
        name: 'Amplitude',
        short_description: 'Amplitude is a product analytics platform that helps you understand your users.',
        description: 'Amplitude is a product analytics platform that helps you understand your users.',
        config_schema: {
            type: 'object',
            properties: {
                api_key: {
                    type: 'string',
                    required: true,
                    placeholder: 'Your Amplitude API key',
                    label: 'API Key',
                },
            },
        },
        icon_url:
            'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAIAAAACFCAMAAACkLQBKAAAAIGNIUk0AAHomAACAhAAA+gAAAIDoAAB1MAAA6mAAADqYAAAXcJy6UTwAAAMAUExURQAAAB5h8BZHsR5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8P///wHlXKQAAAD+dFJOUwAAAAYbOFt/n7vT4u72/P777eHRuZ19WDYZBQkmUYOy1ez5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',
    },
    {
        id: 'optimizely',
        name: 'Optimizely',
        description:
            'Optimizely is a feature management platform that enables teams to deliver continuous experimentation and personalization at scale.',
        short_description: 'Feature management platform',
        icon_url:
            'data:image/png;base64,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',
        config_schema: {
            type: 'object',
            properties: {
                api_key: {
                    type: 'string',
                    title: 'API Key',
                    description: 'Your Optimizely API key.',
                    default: '',
                },
            },
        },
    },
    {
        id: 'taplytics',
        name: 'Taplytics',
        short_description: 'A/B Testing and Feature Management',
        description: 'Taplytics is a mobile A/B testing and feature management platform.',
        icon_url: '',
        config_schema: {
            type: 'object',
            properties: {
                api_key: {
                    type: 'string',
                    title: 'API Key',
                },
            },
        },
    },
    {
        id: 'mixpanel',
        name: 'Mixpanel',
        short_description: 'Analytics',
        description: 'Mixpanel is a mobile analytics platform.',
        icon_url: '',
        config_schema: {
            type: 'object',
            properties: {
                api_key: {
                    type: 'string',
                    title: 'API Key',
                },
            },
        },
    },
]

const destinationTypesLookup = Object.fromEntries(
    destinationTypes.map((destinationType) => [destinationType.id, destinationType])
)

const destinations: Destination[] = [
    {
        id: '1',
        name: 'My Amplitude Destination',
        type: 'amplitude',
        config: {
            api_key: '123',
        },
        stats: {},
    },
    {
        id: '2',
        name: 'My Mixpanel Destination',
        type: 'mixpanel',
        config: {
            api_key: '123',
        },
        stats: {},
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
                '/api/projects/:team_id/destination-types/': {
                    destination_types: destinationTypes,
                },
                '/api/projects/:team_id/destination-types/:type': (req, res, ctx) => {
                    return res(ctx.json(destinationTypesLookup[req.params.type as string]))
                },
                '/api/projects/:team_id/destinations/': {
                    destinations: destinations,
                },
                '/api/projects/:team_id/destinations/:destination_id': (req, res, ctx) => {
                    return res(ctx.json(destinationsLookup[req.params.destination_id as string]))
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
