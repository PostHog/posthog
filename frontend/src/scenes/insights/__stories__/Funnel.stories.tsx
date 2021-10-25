import { Meta } from '@storybook/react'

import { keaStory } from 'lib/storybook/kea-story'

import { Insights } from '../Insights'

import funnelsJson from './funnels.json'
import funnelsWithCorrelationJson from './funnelsWithCorrelation.json'
import { rest } from 'msw'
import { worker } from '../../../mocks/browser'
import { FunnelResult, FunnelStep } from '~/types'
import posthog from 'posthog-js'
import { mockGetPersonProperties } from 'lib/components/TaxonomicFilter/__stories__/TaxonomicFilter.stories'
import { createMemoryHistory } from 'history'
import React from 'react'
import { Provider } from 'kea'
import { initKea } from '~/initKea'

export default {
    title: 'PostHog/Scenes/Insights/Funnel',
} as Meta

export const NoEvents = (): JSX.Element => {
    setFeatureFlags({ 'correlation-analysis': false })

    worker.use(
        rest.post('/api/insight/funnel/', (_, res, ctx) => {
            return res(
                ctx.json({
                    result: [],
                    last_refresh: '2021-10-11T15:00:52.117340Z',
                    is_cached: true,
                } as FunnelResponse)
            )
        })
    )

    return keaStory(Insights, funnelsJson)()
}

export const WithCorrelation = (): JSX.Element => {
    setFeatureFlags({ 'correlation-analysis': true })

    worker.use(
        mockGetPersonProperties((_, res, ctx) =>
            res(
                ctx.json([
                    { id: 1, name: '$geoip_country_code', count: 1 },
                    { id: 2, name: '$os', count: 2 },
                    { id: 3, name: '$browser', count: 3 },
                ])
            )
        ),
        rest.post('/api/insight/funnel/', (_, res, ctx) => {
            return res(ctx.json(sampleFunnelResponse))
        }),
        rest.post<FunnelCorrelationRequest>('/api/insight/funnel/correlation/', (req, res, ctx) =>
            req.body.funnel_correlation_type === 'properties'
                ? res(ctx.json(samplePropertyCorrelationResponse))
                : res(ctx.json(sampleEventCorrelationResponse))
        )
    )

    return keaStory(Insights, funnelsWithCorrelationJson)()
}

export const WithCorrelationAndSkew = (): JSX.Element => {
    setFeatureFlags({ 'correlation-analysis': true })

    worker.use(
        mockGetPersonProperties((_, res, ctx) =>
            res(
                ctx.json([
                    { id: 1, name: '$geoip_country_code', count: 1 },
                    { id: 2, name: '$os', count: 2 },
                    { id: 3, name: '$browser', count: 3 },
                ])
            )
        ),
        rest.post('/api/insight/funnel/', (_, res, ctx) => {
            return res(ctx.json(sampleSkewedFunnelResponse))
        }),
        rest.post<FunnelCorrelationRequest>('/api/insight/funnel/correlation/', (req, res, ctx) =>
            req.body.funnel_correlation_type === 'properties'
                ? res(ctx.json(samplePropertyCorrelationResponse))
                : res(ctx.json(sampleEventCorrelationResponse))
        ),
        rest.get('/api/projects/:projectId/actions/?', (_, res, ctx) => res(ctx.json(sampleActions))),
        rest.get('/api/insight/trend/', (_, res, ctx) => res(ctx.json(sampleInsights))),
        rest.patch('/api/projects/:projectId/insights/', (_, res, ctx) => res(ctx.json(sampleInsights))),
        // rest.get('/_preflight/', (_, res, ctx) => res(ctx.json({}))),
        rest.get('/api/projects/@current/property_definitions/', (_, res, ctx) => res(ctx.json(sampleProperties))),
        rest.get('/api/projects/@current/event_definitions/', (_, res, ctx) => res(ctx.json(sampleEvents))),
        rest.get('/api/insight/471605/', (_, res, ctx) => res(ctx.json(sampleInsights)))
        // rest.get('*', (_, res, ctx) => res(ctx.json({}))),
        // rest.post('*', (_, res, ctx) => res(ctx.json({})))
    )

    const history = createMemoryHistory({
        initialEntries: [
            '/insights?insight=FUNNELS&properties=%5B%5D&filter_test_accounts=false&events=%5B%7B%22id%22%3A%22%24pageview%22%2C%22name%22%3A%22%24pageview%22%2C%22type%22%3A%22events%22%2C%22order%22%3A0%7D%2C%7B%22id%22%3A%22%24pageview%22%2C%22name%22%3A%22%24pageview%22%2C%22type%22%3A%22events%22%2C%22order%22%3A1%7D%2C%7B%22id%22%3A%22%24pageview%22%2C%22name%22%3A%22%24pageview%22%2C%22type%22%3A%22events%22%2C%22order%22%3A2%7D%5D&actions=%5B%5D&funnel_viz_type=steps&display=FunnelViz&interval=day&new_entity=%5B%5D&date_from=-14dinsight=FUNNELS&actions=%5B%5D&events=%5B%7B"id"%3A"%24pageview"%2C"name"%3A"%24pageview"%2C"type"%3A"events"%2C"order"%3A0%7D%2C%7B"id"%3A"%24pageview"%2C"name"%3A"%24pageview"%2C"type"%3A"events"%2C"order"%3A1%7D%5D&display=FunnelViz&interval=day&properties=%5B%5D&funnel_viz_type=steps&exclusions=%5B%5D&funnel_from_step=0&funnel_to_step=1#fromItem=471605',
        ],
    })

    // @ts-ignore
    history.pushState = history.push
    // @ts-ignore
    history.replaceState = history.replace

    initKea({ routerHistory: history, routerLocation: history.location })

    return (
        <Provider>
            <Insights />
        </Provider>
    )
}

const setFeatureFlags = (featureFlags: { [flag: string]: boolean }): void => {
    // Allows for specifying featureflags to be enabled/disabled. It relies on
    // MSW.
    worker.use(
        rest.post('/decide/', (_, res, ctx) => {
            return res(ctx.json({ featureFlags }))
        })
    )

    // Trigger a reload of featureflags, as we could be using locally cached
    // ones
    posthog.reloadFeatureFlags()
}

// Types that should be defined elsewhere within an api cli

// I tried to use `FunnelResult` from `types.ts` but it seems to not match up
// with the request format I copied from a production api request. specifically,
// `FunnelResult` expects a `type` property, and doesn't expect
// `median_conversion_time`, and custom_name is not `string | undefined`
type FunnelResponse = Omit<
    FunnelResult<
        (Omit<FunnelStep, 'custom_name'> & { median_conversion_time: number | null; custom_name: string | null })[]
    >,
    'type'
>

type FunnelCorrelationRequest = {
    funnel_correlation_type: 'events' | 'properties'
}

type FunnelCorrelationResponse = {
    result: {
        events: {
            event: string
            odds_ratio: number
            success_count: number
            failure_count: number
            correlation_type: 'success' | 'failure'
        }[]
        skewed: boolean
    }
    last_refresh: string
    is_cached: boolean
}

// Sample responses used in stories
const samplePropertyCorrelationResponse: FunnelCorrelationResponse = {
    result: {
        events: [
            {
                event: '$geoip_country_code::IE',
                success_count: 65,
                failure_count: 12,
                odds_ratio: 9.709598031173092,
                correlation_type: 'success',
            },
            {
                event: '$os::Mac OS X',
                success_count: 1737,
                failure_count: 1192,
                odds_ratio: 4.267011809020293,
                correlation_type: 'success',
            },
            {
                event: '$browser::Firefox',
                success_count: 382,
                failure_count: 192,
                odds_ratio: 4.048527814836648,
                correlation_type: 'success',
            },
        ],
        skewed: false,
    },
    last_refresh: '2021-10-11T15:00:54.248787Z',
    is_cached: true,
}

const sampleEventCorrelationResponse: FunnelCorrelationResponse = {
    result: {
        events: [
            {
                event: 'person viewed',
                success_count: 59,
                failure_count: 0,
                odds_ratio: 114.75839475839476,
                correlation_type: 'success',
            },
            {
                event: 'select edition: clicked get started',
                success_count: 42,
                failure_count: 0,
                odds_ratio: 81.86358695652174,
                correlation_type: 'success',
            },
            {
                event: 'insight viewed',
                success_count: 396,
                failure_count: 1300,
                odds_ratio: 0.621617558628984,
                correlation_type: 'failure',
            },
        ],
        skewed: false,
    },
    last_refresh: '2021-10-11T15:00:54.687382Z',
    is_cached: true,
}

const sampleFunnelResponse: FunnelResponse = {
    result: [
        {
            action_id: '$pageview',
            name: '$pageview',
            custom_name: null,
            order: 0,
            people: ['017c567f-1f26-0000-bdb3-d29a6484acb6'],
            count: 10726,
            type: 'events',
            average_conversion_time: null,
            median_conversion_time: null,
        },
        {
            action_id: '$pageview',
            name: '$pageview',
            custom_name: null,
            order: 1,
            people: ['017c567f-1f26-0000-bdb3-d29a6484acb6'],
            count: 7627,
            type: 'events',
            average_conversion_time: 3605.594525238891,
            median_conversion_time: 2.0,
        },
        {
            action_id: '$pageview',
            name: '$pageview',
            custom_name: null,
            order: 2,
            people: ['017c567f-1f26-0000-bdb3-d29a6484acb6'],
            count: 3721,
            type: 'events',
            average_conversion_time: 7734.935688918132,
            median_conversion_time: 6.0,
        },
    ],
    last_refresh: '2021-10-11T15:00:52.117340Z',
    is_cached: true,
}

const sampleSkewedFunnelResponse: FunnelResponse = {
    result: [
        {
            action_id: '$pageview',
            name: '$pageview',
            custom_name: null,
            order: 0,
            people: ['017c567f-1f26-0000-bdb3-d29a6484acb6'],
            count: 10726,
            type: 'events',
            average_conversion_time: null,
            median_conversion_time: null,
        },
        {
            action_id: '$pageview',
            name: '$pageview',
            custom_name: null,
            order: 1,
            people: ['017c567f-1f26-0000-bdb3-d29a6484acb6'],
            count: 7627,
            type: 'events',
            average_conversion_time: 3605.594525238891,
            median_conversion_time: 2.0,
        },
        {
            action_id: '$pageview',
            name: '$pageview',
            custom_name: null,
            order: 2,
            people: ['017c567f-1f26-0000-bdb3-d29a6484acb6'],
            count: 10,
            type: 'events',
            average_conversion_time: 7734.935688918132,
            median_conversion_time: 6.0,
        },
    ],
    last_refresh: '2021-10-11T15:00:52.117340Z',
    is_cached: true,
}

const sampleActions = {
    results: [],
}

const sampleInsights = {
    id: 471605,
    short_id: 'e2q24fy7',
    name: null,
    filters: {
        insight: 'FUNNELS',
        actions: [],
        events: [
            { id: '$pageview', name: '$pageview', type: 'events', order: 0 },
            { id: '$pageview', name: '$pageview', type: 'events', order: 1 },
        ],
        display: 'FunnelViz',
        interval: 'day',
        properties: [],
        funnel_viz_type: 'steps',
        exclusions: [],
        funnel_from_step: 0,
        funnel_to_step: 1,
    },
    filters_hash: 'cache_fcaabdbdff7df6efe226521758a91832',
    order: null,
    deleted: false,
    dashboard: null,
    dive_dashboard: null,
    layouts: {},
    color: null,
    last_refresh: null,
    refreshing: false,
    result: [
        {
            action_id: '$pageview',
            name: '$pageview',
            custom_name: null,
            order: 0,
            people: ['017cb1ec-5939-0000-262b-c1149bb3adbd'],
            count: 9936,
            type: 'events',
            average_conversion_time: null,
            median_conversion_time: null,
        },
        {
            action_id: '$pageview',
            name: '$pageview',
            custom_name: null,
            order: 1,
            people: ['017cb1ec-5939-0000-262b-c1149bb3adbd'],
            count: 8470,
            type: 'events',
            average_conversion_time: 3259.2458615695127,
            median_conversion_time: 2.0,
        },
    ],
    created_at: '2021-10-25T17:25:58.388607Z',
    description: null,
    updated_at: '2021-10-25T17:37:48.876139Z',
    tags: [],
    favorited: false,
    saved: false,
    created_by: {
        id: 4973,
        uuid: '017bbadc-f13d-0000-da28-c962b0a6d89f',
        distinct_id: 'E6wBts6SmoYJOx1LXgfbYWkVoUaxlHqV03nHMoMCYvX',
        first_name: 'Harry',
        email: 'harry@posthog.com',
    },
    is_sample: false,
}

const sampleProperties = {
    count: 11668,
    next: null,
    previous: null,
    results: [],
}

const sampleEvents = {
    count: 292,
    next: null,
    previous: null,
    results: [],
}
