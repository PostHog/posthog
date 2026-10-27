import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const MOCK_PROPERTY_DEFINITIONS = {
    count: 5,
    next: null,
    previous: null,
    results: [
        {
            id: '1',
            name: '$browser',
            description: 'The browser used by the user',
            tags: ['web'],
            property_type: 'String',
            type: 1,
            verified: true,
        },
        {
            id: '2',
            name: '$os',
            description: 'The operating system of the user',
            tags: ['web'],
            property_type: 'String',
            type: 1,
            verified: true,
        },
        {
            id: '3',
            name: 'plan',
            description: 'User subscription plan',
            tags: ['billing'],
            property_type: 'String',
            type: 1,
            verified: false,
        },
        {
            id: '4',
            name: 'revenue',
            description: 'Revenue amount',
            tags: ['billing', 'revenue'],
            property_type: 'Numeric',
            type: 1,
            is_numerical: true,
            verified: false,
        },
        {
            id: '5',
            name: '$current_url',
            description: 'The current URL of the page',
            tags: [],
            property_type: 'String',
            type: 1,
            verified: true,
        },
    ],
}

const MOCK_QUERY_USAGE: Record<string, number> = { $browser: 4210, $os: 1388, plan: 52, $current_url: 9934 }

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Data Management/Property Definitions',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-03-31',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/property_definitions/': ({ request }) => {
                    const verified = new URL(request.url).searchParams.get('verified')
                    let results = MOCK_PROPERTY_DEFINITIONS.results

                    if (verified === 'true') {
                        results = results.filter((p) => p.verified === true)
                    } else if (verified === 'false') {
                        results = results.filter((p) => !p.verified)
                    }

                    return [200, { ...MOCK_PROPERTY_DEFINITIONS, results, count: results.length }]
                },
            },
            post: {
                '/api/projects/:team_id/property_definitions/usage_metrics/': async ({ request }) => {
                    const { properties } = (await request.json()) as { properties: { name: string }[] }
                    return [
                        200,
                        {
                            results: properties.map(({ name }) => ({
                                type: 'event',
                                name,
                                group_type_index: null,
                                query_usage_30_day: MOCK_QUERY_USAGE[name] ?? 0,
                            })),
                        },
                    ]
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const Default: Story = {
    parameters: {
        pageUrl: urls.propertyDefinitions(),
    },
}

export const FilteredVerifiedOnly: Story = {
    parameters: {
        pageUrl: urls.propertyDefinitions() + '?verified=true',
    },
}

export const FilteredUnverifiedOnly: Story = {
    parameters: {
        pageUrl: urls.propertyDefinitions() + '?verified=false',
    },
}
