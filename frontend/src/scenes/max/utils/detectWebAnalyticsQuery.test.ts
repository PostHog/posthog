import { AssistantMessageType } from '~/queries/schema/schema-assistant-messages'
import { NodeKind } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import { ThreadMessage } from '../maxThreadLogic'
import {
    isWebAnalyticsRelatedMessage,
    isWebAnalyticsRelatedQuery,
    isWebAnalyticsRelatedQuestion,
} from './detectWebAnalyticsQuery'

const pageviewTrends = {
    kind: NodeKind.TrendsQuery,
    series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
} as any

const referrerBreakdownTrends = {
    kind: NodeKind.TrendsQuery,
    series: [{ kind: NodeKind.EventsNode, event: 'click' }],
    breakdownFilter: { breakdown: '$referring_domain' },
} as any

const currentUrlPropertyTrends = {
    kind: NodeKind.TrendsQuery,
    series: [{ kind: NodeKind.EventsNode, event: 'click' }],
    properties: [
        {
            key: '$current_url',
            type: PropertyFilterType.Event,
            operator: PropertyOperator.IContains,
            value: 'pricing',
        },
    ],
} as any

const nestedUtmGroupTrends = {
    kind: NodeKind.TrendsQuery,
    series: [{ kind: NodeKind.EventsNode, event: 'click' }],
    properties: {
        type: FilterLogicalOperator.And,
        values: [
            {
                type: FilterLogicalOperator.Or,
                values: [
                    {
                        key: 'utm_source',
                        type: PropertyFilterType.Event,
                        operator: PropertyOperator.Exact,
                        value: 'google',
                    },
                ],
            },
        ],
    },
} as any

const pageviewPaths = {
    kind: NodeKind.PathsQuery,
    pathsFilter: { includeEventTypes: ['$pageview'] },
} as any

const insightVizWrappingPageview = {
    kind: NodeKind.InsightVizNode,
    source: pageviewTrends,
} as any

const dataVizWithPathname = {
    kind: NodeKind.DataVisualizationNode,
    source: {
        kind: NodeKind.HogQLQuery,
        query: "SELECT count() FROM events WHERE properties.$pathname = '/home'",
    },
} as any

const webOverviewQuery = { kind: NodeKind.WebOverviewQuery } as any

const nonWebTrends = {
    kind: NodeKind.TrendsQuery,
    series: [{ kind: NodeKind.EventsNode, event: 'signed_up' }],
    properties: [
        {
            key: 'plan',
            type: PropertyFilterType.Event,
            operator: PropertyOperator.Exact,
            value: 'pro',
        },
    ],
} as any

const nonWebFunnel = {
    kind: NodeKind.FunnelsQuery,
    series: [
        { kind: NodeKind.EventsNode, event: 'signed_up' },
        { kind: NodeKind.EventsNode, event: 'activated' },
    ],
} as any

describe('detectWebAnalyticsQuery', () => {
    describe('isWebAnalyticsRelatedQuery', () => {
        it.each([
            ['pageview trends series', pageviewTrends],
            ['referring_domain breakdown', referrerBreakdownTrends],
            ['current_url property filter', currentUrlPropertyTrends],
            ['nested utm_source property group', nestedUtmGroupTrends],
            ['pageview paths includeEventTypes', pageviewPaths],
            ['insightVizNode wrapping pageview trends', insightVizWrappingPageview],
            ['dataVisualizationNode with $pathname sql', dataVizWithPathname],
            ['bare WebOverviewQuery', webOverviewQuery],
        ])('returns true for %s', (_label, query) => {
            expect(isWebAnalyticsRelatedQuery(query)).toBe(true)
        })

        it.each([
            ['non-web trends', nonWebTrends],
            ['non-web funnel', nonWebFunnel],
            ['null', null],
            ['undefined', undefined],
            ['malformed empty object', {} as any],
        ])('returns false for %s', (_label, query) => {
            expect(isWebAnalyticsRelatedQuery(query)).toBe(false)
        })

        it('does not throw on deeply malformed input', () => {
            const malformed = { kind: NodeKind.TrendsQuery, series: [{ kind: NodeKind.GroupNode }] } as any
            expect(() => isWebAnalyticsRelatedQuery(malformed)).not.toThrow()
            expect(isWebAnalyticsRelatedQuery(malformed)).toBe(false)
        })
    })

    describe('isWebAnalyticsRelatedQuestion', () => {
        it.each([
            'where is my traffic coming from?',
            'show me pageviews',
            'what is my bounce rate',
            'top pages last week',
        ])('returns true for %s', (text) => {
            expect(isWebAnalyticsRelatedQuestion(text)).toBe(true)
        })

        it.each([
            'how many users signed up?',
            'revenue by month',
            'how did our email campaign perform?',
            'did users visit the new onboarding flow?',
            '',
        ])('returns false for %s', (text) => {
            expect(isWebAnalyticsRelatedQuestion(text)).toBe(false)
        })

        it.each([null, undefined])('returns false for nullish input', (text) => {
            expect(isWebAnalyticsRelatedQuestion(text)).toBe(false)
        })
    })

    describe('isWebAnalyticsRelatedMessage', () => {
        it('returns true for an artifact visualization with a web analytics related query', () => {
            const message = {
                type: AssistantMessageType.Artifact,
                content: {
                    content_type: 'visualization',
                    query: pageviewTrends,
                },
            } as any as ThreadMessage
            expect(isWebAnalyticsRelatedMessage(message)).toBe(true)
        })

        it('returns true for a multi-visualization where one viz is web analytics related', () => {
            const message = {
                type: AssistantMessageType.MultiVisualization,
                visualizations: [
                    { query: '', answer: nonWebTrends },
                    { query: '', answer: pageviewTrends },
                ],
            } as any as ThreadMessage
            expect(isWebAnalyticsRelatedMessage(message)).toBe(true)
        })

        it('returns true for a legacy visualization message with a web analytics related answer', () => {
            const message = {
                type: AssistantMessageType.Visualization,
                query: '',
                answer: pageviewTrends,
            } as any as ThreadMessage
            expect(isWebAnalyticsRelatedMessage(message)).toBe(true)
        })

        it('returns false for a plain assistant text message', () => {
            const message = {
                type: AssistantMessageType.Assistant,
                content: 'Here is your answer',
            } as any as ThreadMessage
            expect(isWebAnalyticsRelatedMessage(message)).toBe(false)
        })

        it('returns false for a multi-visualization with no web signals', () => {
            const message = {
                type: AssistantMessageType.MultiVisualization,
                visualizations: [{ query: '', answer: nonWebTrends }],
            } as any as ThreadMessage
            expect(isWebAnalyticsRelatedMessage(message)).toBe(false)
        })
    })
})
