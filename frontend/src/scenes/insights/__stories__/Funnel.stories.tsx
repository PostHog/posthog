import { Meta } from '@storybook/react'

import { keaStory } from 'lib/storybook/kea-story'

import { Insights } from '../Insights'

import funnelsJson from './funnels.json'
import funnelsWithCorrelationJson from './funnelsWithCorrelation.json'
import { rest } from 'msw'
import { worker } from '../../../mocks/browser'
import { FunnelResult, FunnelStep } from '~/types'
import posthog from 'posthog-js'

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
        rest.post('/api/insight/funnel/', (_, res, ctx) => {
            return res(ctx.json(sampleSkewedFunnelResponse))
        }),
        rest.post<FunnelCorrelationRequest>('/api/insight/funnel/correlation/', (req, res, ctx) =>
            req.body.funnel_correlation_type === 'properties'
                ? res(ctx.json(samplePropertyCorrelationResponse))
                : res(ctx.json(sampleEventCorrelationResponse))
        )
    )

    return keaStory(Insights, funnelsWithCorrelationJson)()
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
