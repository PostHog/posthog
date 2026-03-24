// Stories for Customer Analytics Journey Templates scene
import { Meta, StoryFn } from '@storybook/react'

import { App } from 'scenes/App'
import { JOURNEY_FEATURE_FLAGS } from 'scenes/funnels/FunnelFlowGraph/__mocks__/journeyMocks'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { NodeKind } from '~/queries/schema/schema-general'

const SAMPLE_FUNNELS = {
    count: 2,
    results: [
        {
            id: 101,
            short_id: 'funnel-1',
            name: 'Onboarding Funnel',
            description: 'Tracks user onboarding steps',
            saved: true,
            query: {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.FunnelsQuery,
                    series: [
                        { kind: NodeKind.EventsNode, event: '$pageview', name: 'Pageview' },
                        { kind: NodeKind.EventsNode, event: 'sign_up', name: 'Sign up' },
                    ],
                    funnelsFilter: { funnelVizType: 'steps' },
                },
            },
            result: null,
            created_at: '2024-01-01T00:00:00Z',
            last_modified_at: '2024-01-10T00:00:00Z',
            tags: ['onboarding'],
            dashboards: [],
        },
        {
            id: 102,
            short_id: 'funnel-2',
            name: 'Checkout Funnel',
            description: 'Cart to payment flow',
            saved: true,
            query: {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.FunnelsQuery,
                    series: [
                        { kind: NodeKind.EventsNode, event: 'add_to_cart', name: 'Add to cart' },
                        { kind: NodeKind.EventsNode, event: 'purchase', name: 'Purchase' },
                    ],
                    funnelsFilter: { funnelVizType: 'steps' },
                },
            },
            result: null,
            created_at: '2024-01-05T00:00:00Z',
            last_modified_at: '2024-01-12T00:00:00Z',
            tags: ['revenue'],
            dashboards: [],
        },
    ],
}

const CONFIGURED_EVENTS = {
    customer_analytics_config: {
        signup_event: { kind: 'EventsNode', event: 'sign_up', name: 'Sign up' },
        signup_pageview_event: { kind: 'EventsNode', event: '$pageview', name: 'Pageview' },
        payment_event: { kind: 'EventsNode', event: 'purchase', name: 'Purchase' },
        activity_event: { kind: 'EventsNode', event: '$pageview', name: 'Pageview' },
        subscription_event: {},
    },
}

const EMPTY_EVENTS = {
    customer_analytics_config: {
        signup_event: {},
        signup_pageview_event: {},
        payment_event: {},
        activity_event: {},
        subscription_event: {},
    },
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Customer Analytics/Journey Templates',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2024-01-15',
        featureFlags: JOURNEY_FEATURE_FLAGS,
    },
    decorators: [
        mswDecorator({
            get: {
                'api/environments/:team_id/customer_profile_configs/': { count: 0, results: [] },
                'api/environments/:team_id/customer_journeys/': { count: 0, results: [] },
                'api/environments/:team_id/insights/': SAMPLE_FUNNELS,
            },
        }),
    ],
}
export default meta

export const TemplatesWithEventsConfigured: StoryFn = () => {
    useStorybookMocks({
        get: {
            'api/environments/:team_id/': { ...CONFIGURED_EVENTS },
        },
    })
    return <App />
}
TemplatesWithEventsConfigured.parameters = {
    pageUrl: urls.customerJourneyTemplates(),
    testOptions: { waitForSelector: '[data-attr="journey-template-card-scratch"]' },
}

export const TemplatesWithoutEventsConfigured: StoryFn = () => {
    useStorybookMocks({
        get: {
            'api/environments/:team_id/': { ...EMPTY_EVENTS },
        },
    })
    return <App />
}
TemplatesWithoutEventsConfigured.parameters = {
    pageUrl: urls.customerJourneyTemplates(),
    testOptions: { waitForSelector: '[data-attr="journey-template-card-scratch"]' },
}
