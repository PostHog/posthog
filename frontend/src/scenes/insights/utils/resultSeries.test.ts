import { InsightQueryNode, NodeKind } from '~/queries/schema/schema-general'
import { BaseMathType } from '~/types'

import { ResultSeries, ResultSeriesRow, getResultSeries } from './resultSeries'

describe('getResultSeries()', () => {
    const pageviews = { kind: NodeKind.EventsNode as const, event: '$pageview', name: '$pageview' }
    const signups = { kind: NodeKind.ActionsNode as const, id: 7, name: 'Signed up' }

    it.each<{ case: string; query: InsightQueryNode; row: ResultSeriesRow; expected: ResultSeries }>([
        {
            case: 'a formula row to no series, although its order is a valid series index',
            query: {
                kind: NodeKind.TrendsQuery,
                series: [pageviews, signups],
                trendsFilter: { formulaNodes: [{ formula: 'A+B' }, { formula: 'A/B' }] },
            },
            row: { order: 1, action: null },
            expected: { order: 1, node: null, math: null },
        },
        {
            case: 'a stickiness row by the order it carries only on action',
            query: { kind: NodeKind.StickinessQuery, series: [pageviews, signups] },
            row: { action: { order: 1, name: 'Signed up' } },
            expected: { order: 1, node: signups, math: {} },
        },
        {
            case: 'weekly active users on a weekly interval to the daily math the runner applies',
            query: {
                kind: NodeKind.TrendsQuery,
                interval: 'week',
                series: [{ ...pageviews, math: BaseMathType.WeeklyActiveUsers }],
            },
            row: { order: 0 },
            expected: {
                order: 0,
                node: { ...pageviews, math: BaseMathType.WeeklyActiveUsers },
                math: { math: BaseMathType.UniqueUsers },
            },
        },
        {
            case: 'an events series saved without a name to its event',
            query: { kind: NodeKind.TrendsQuery, series: [{ kind: NodeKind.EventsNode, event: '$autocapture' }] },
            row: { order: 0 },
            expected: {
                order: 0,
                node: { kind: NodeKind.EventsNode, event: '$autocapture', name: '$autocapture' },
                math: {},
            },
        },
        {
            case: 'an action series saved without a name to the name the runner resolved',
            query: { kind: NodeKind.TrendsQuery, series: [{ kind: NodeKind.ActionsNode, id: 7 }] },
            row: { order: 0, action: { order: 0, name: 'Signed up' } },
            expected: { order: 0, node: { kind: NodeKind.ActionsNode, id: 7, name: 'Signed up' }, math: {} },
        },
    ])('resolves $case', ({ query, row, expected }) => {
        expect(getResultSeries(query, row)).toEqual(expected)
    })
})
