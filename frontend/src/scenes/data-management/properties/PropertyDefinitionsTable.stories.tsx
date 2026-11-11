import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
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

const QUERY_COUNTS: Record<string, number> = { $browser: 1284, $os: 312, plan: 0, revenue: 57, $current_url: 9_431 }
const LAST_SENT: Record<string, { last_sent_status: string; last_sent_at: string | null }> = {
    $current_url: { last_sent_status: 'sent', last_sent_at: '2026-11-12T03:00:00Z' },
    $browser: { last_sent_status: 'sent', last_sent_at: '2026-11-11T16:00:00Z' },
    $os: { last_sent_status: 'sent', last_sent_at: '2026-11-06T09:00:00Z' },
    plan: { last_sent_status: 'not_sent_in_30_days', last_sent_at: null },
    revenue: { last_sent_status: 'not_tracked', last_sent_at: null },
}

export const WithQueryCountsSortedByMostQueried: Story = {
    parameters: {
        pageUrl: urls.propertyDefinitions() + '?ordering=-query_usage',
        featureFlags: [FEATURE_FLAGS.DEFINITION_USAGE_SECTION],
        mockDate: '2026-11-12T10:08:00Z',
        testOptions: {
            waitForSelector: '[data-attr="property-definitions-query-usage-coverage"]',
            snapshotBrowsers: [],
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/property_definitions/': () => [
                    200,
                    {
                        ...MOCK_PROPERTY_DEFINITIONS,
                        results: MOCK_PROPERTY_DEFINITIONS.results
                            .map((definition) => ({
                                ...definition,
                                type: 'event',
                                query_usage_30_day: QUERY_COUNTS[definition.name] ?? 0,
                                ...LAST_SENT[definition.name],
                            }))
                            .sort((a, b) => b.query_usage_30_day - a.query_usage_30_day),
                        query_usage: {
                            computed_at: '2026-11-12T10:00:00Z',
                            tracking_since: '2026-11-03T09:00:00Z',
                        },
                        last_sent: { status: 'ready', computed_at: '2026-11-12T09:40:00Z' },
                    },
                ],
            },
        }),
    ],
}

export const UsageSortRefusedForLargeProject: Story = {
    parameters: {
        pageUrl: urls.propertyDefinitions() + '?ordering=query_usage',
        featureFlags: [FEATURE_FLAGS.DEFINITION_USAGE_SECTION],
        testOptions: {
            waitForSelector: '[data-attr="property-definitions-clear-usage-sort"]',
            snapshotBrowsers: [],
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/property_definitions/': () => [
                    400,
                    {
                        type: 'validation_error',
                        code: 'too_many_properties_to_order_by_usage',
                        detail: 'There are too many properties to sort by queries. Search or filter the list, then sort again.',
                        attr: null,
                    },
                ],
            },
        }),
    ],
}
