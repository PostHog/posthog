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
import { EventType } from '~/types'

// Needed to be able to interact with project level correlation settings
let correlationConfig: any = null

export default {
    title: 'PostHog/Scenes/Insights/Funnel',
    decorators: [
        (Story) => {
            worker.use(
                rest.get('/api/projects/:projectId', (_, res, ctx) => {
                    return res(ctx.json({ id: 2, correlation_config: correlationConfig }))
                }),
                rest.patch('/api/projects/:projectId', (req, res, ctx) => {
                    correlationConfig = (req.body as { correlation_config: any }).correlation_config
                    return res(ctx.json({ id: 2, correlation_config: correlationConfig }))
                })
            )

            return <Story />
        },
    ],
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
        rest.post('/api/projects/:projectId/insights/funnel/', (_, res, ctx) =>
            res(ctx.json(sampleSkewedFunnelResponse))
        ),
        rest.post<FunnelCorrelationRequest>('/api/projects/:projectId/insights/funnel/correlation/', (req, res, ctx) =>
            req.body.funnel_correlation_type === 'properties'
                ? res(ctx.json(samplePropertyCorrelationResponse))
                : req.body.funnel_correlation_type === 'events'
                ? res(ctx.json(sampleEventCorrelationResponse))
                : res(ctx.json(sampleEventWithPropertyCorrelationResponse))
        )
    )

    const history = createMemoryHistory({
        initialEntries: [
            `/insights?${new URLSearchParams({
                insight: 'FUNNELS',
                properties: JSON.stringify([]),
                filter_test_accounts: 'false',
                events: JSON.stringify([
                    { id: '$pageview', name: '$pageview', type: 'events', order: 0 },
                    { id: '$pageview', name: '$pageview', type: 'events', order: 1 },
                    { id: '$pageview', name: '$pageview', type: 'events', order: 2 },
                ]),
                actions: JSON.stringify([]),
                funnel_viz_type: 'steps',
                display: 'FunnelViz',
                interval: 'day',
                new_entity: JSON.stringify([]),
                date_from: '-14d',
                exclusions: JSON.stringify([]),
                funnel_from_step: '0',
                funnel_to_step: '1',
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
            event: Partial<EventType>
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
                event: {
                    event: '$geoip_country_code::IE',
                },
                success_count: 65,
                failure_count: 12,
                odds_ratio: 9.709598031173092,
                correlation_type: 'success',
            },
            {
                event: {
                    event: '$os::Mac OS X',
                },
                success_count: 1737,
                failure_count: 1192,
                odds_ratio: 4.267011809020293,
                correlation_type: 'success',
            },
            {
                event: {
                    event: '$browser::Firefox',
                },
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
                event: {
                    event: 'person viewed',
                },
                success_count: 59,
                failure_count: 0,
                odds_ratio: 114.75839475839476,
                correlation_type: 'success',
            },
            {
                event: {
                    event: 'select edition: clicked get started',
                },
                success_count: 42,
                failure_count: 0,
                odds_ratio: 81.86358695652174,
                correlation_type: 'success',
            },
            {
                event: {
                    event: 'insight viewed',
                },
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

const sampleEventWithPropertyCorrelationResponse: FunnelCorrelationResponse = {
    result: {
        events: [
            {
                success_count: 155,
                failure_count: 0,
                odds_ratio: 27.594682835820894,
                correlation_type: 'success',
                event: { event: 'section heading viewed::$feature/new-paths-ui::true', properties: {}, elements: [] },
            },
            {
                success_count: 150,
                failure_count: 0,
                odds_ratio: 26.694674280386902,
                correlation_type: 'success',
                event: { event: 'section heading viewed::$lib_version::1.15.3', properties: {}, elements: [] },
            },
            {
                success_count: 155,
                failure_count: 1,
                odds_ratio: 13.788246268656716,
                correlation_type: 'success',
                event: {
                    event: 'section heading viewed::$feature/4156-tooltips-legends::true',
                    properties: {},
                    elements: [],
                },
            },
        ],
        skewed: false,
    },
    last_refresh: '2021-10-26T15:36:39.921274Z',
    is_cached: false,
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
