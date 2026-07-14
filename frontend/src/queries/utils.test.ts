import { MOCK_TEAM_ID } from 'lib/api.mock'

import { dayjs } from 'lib/dayjs'
import { getAppContext } from 'lib/utils/getAppContext'
import { teamLogic } from 'scenes/teamLogic'

import { DataTableNode, DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import type { InsightQueryNode } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AppContext, ChartDisplayType, FunnelVizType, TeamType } from '~/types'

import {
    convertDataTableNodeToDataVisualizationNode,
    escapeDottedHogQLIdentifier,
    escapeHogQLString,
    escapePropertyAsHogQLIdentifier,
    hogql,
    queryVizRendersToCanvas,
    supportsBarValueStacking,
} from './utils'

window.POSTHOG_APP_CONTEXT = { current_team: { id: MOCK_TEAM_ID } } as unknown as AppContext

describe('hogql tag', () => {
    // In beforeEach (not describe scope): mounting at collection time fires the preflight
    // load before the MSW harness's beforeAll has installed its fetch stub
    beforeEach(() => {
        initKeaTests()
        teamLogic.mount()
    })

    it('properly returns query with no substitutions', () => {
        expect(hogql`SELECT * FROM events`).toEqual('SELECT * FROM events')
    })

    it('properly returns query with simple identifier substition', () => {
        expect(hogql`SELECT * FROM ${hogql.identifier('events')}`).toEqual('SELECT * FROM events')
    })

    it('properly returns query with escaped identifier substition', () => {
        expect(hogql`SELECT properties.${hogql.identifier('odd property')} FROM events`).toEqual(
            'SELECT properties."odd property" FROM events'
        )
    })

    it('properly returns query with string and number substitutions', () => {
        expect(hogql`SELECT * FROM events WHERE properties.foo = ${'bar'} AND properties.baz = ${3}`).toEqual(
            "SELECT * FROM events WHERE properties.foo = 'bar' AND properties.baz = 3"
        )
    })

    it('properly returns query with string array substitution', () => {
        expect(hogql`SELECT * FROM events WHERE properties.foo IN ${['bar', 'baz']}`).toEqual(
            "SELECT * FROM events WHERE properties.foo IN ['bar', 'baz']"
        )
    })

    it('properly returns query with date substitution in UTC', () => {
        teamLogic.actions.loadCurrentTeamSuccess({ id: MOCK_TEAM_ID, timezone: 'UTC' } as TeamType)
        expect(hogql`SELECT * FROM events WHERE timestamp > ${dayjs('2023-04-04T04:04:00Z')}`).toEqual(
            "SELECT * FROM events WHERE timestamp > '2023-04-04 04:04:00'"
        )
    })

    it('properly returns query with date substitution in non-UTC', () => {
        const context = getAppContext()
        let oldTimezone = context?.current_team?.timezone || 'UTC'
        if (context?.current_team) {
            context.current_team.timezone = 'Europe/Moscow'
        }
        teamLogic.actions.loadCurrentTeamSuccess({ id: MOCK_TEAM_ID, timezone: 'Europe/Moscow' } as TeamType)
        expect(hogql`SELECT * FROM events WHERE timestamp > ${dayjs('2023-04-04T04:04:00Z')}`).toEqual(
            "SELECT * FROM events WHERE timestamp > '2023-04-04 07:04:00'" // Offset by 3 hours
        )
        if (context?.current_team) {
            context.current_team.timezone = oldTimezone
        }
    })

    it('properly escapes single quotes in string values', () => {
        expect(hogql`SELECT * FROM events WHERE properties.name = ${"O'Reilly"}`).toEqual(
            "SELECT * FROM events WHERE properties.name = 'O\\'Reilly'"
        )
    })

    it('properly escapes backslashes in string values', () => {
        expect(hogql`SELECT * FROM events WHERE properties.path = ${'C:\\Users\\test'}`).toEqual(
            "SELECT * FROM events WHERE properties.path = 'C:\\\\Users\\\\test'"
        )
    })
})

describe('escapeHogQLString', () => {
    it.each([
        ['simple', "'simple'"],
        ["O'Reilly", "'O\\'Reilly'"],
        ["'; DROP TABLE users; --", "'\\'; DROP TABLE users; --'"],
        ['C:\\Users\\test', "'C:\\\\Users\\\\test'"],
        ['line1\nline2', "'line1\\nline2'"],
        ['tab\there', "'tab\\there'"],
        ['carriage\rreturn', "'carriage\\rreturn'"],
        ['', "''"],
        ["multiple'quotes'here", "'multiple\\'quotes\\'here'"],
        ['back\\slash', "'back\\\\slash'"],
    ])('escapes %s to %s', (input, expected) => {
        expect(escapeHogQLString(input)).toEqual(expected)
    })
})

describe('escapePropertyAsHogQLIdentifier', () => {
    it('leaves simple identifiers unquoted', () => {
        expect(escapePropertyAsHogQLIdentifier('browser')).toEqual('browser')
        expect(escapePropertyAsHogQLIdentifier('$browser')).toEqual('$browser')
    })

    it('double-quotes identifiers with special characters but no double quote', () => {
        expect(escapePropertyAsHogQLIdentifier('order items')).toEqual('"order items"')
    })

    it('backtick-wraps identifiers containing a double quote', () => {
        expect(escapePropertyAsHogQLIdentifier('a"b')).toEqual('`a"b`')
    })

    it('doubles inner backticks when an identifier has both a double quote and a backtick', () => {
        // Backslash-escaping (`a"b\`c`) would be rejected by the HogQL parser; doubling round-trips.
        expect(escapePropertyAsHogQLIdentifier('a"b`c')).toEqual('`a"b``c`')
    })

    it('escapes backslashes so they survive the parser instead of forming an escape sequence', () => {
        expect(escapePropertyAsHogQLIdentifier('a\\b')).toEqual('"a\\\\b"')
        expect(escapePropertyAsHogQLIdentifier('end\\')).toEqual('"end\\\\"')
        // A backslash alongside a double quote takes the backtick branch and still escapes both.
        expect(escapePropertyAsHogQLIdentifier('a"\\b')).toEqual('`a"\\\\b`')
        // A backslash immediately before an inner backtick (which forces the backtick branch).
        expect(escapePropertyAsHogQLIdentifier('a"b\\`c')).toEqual('`a"b\\\\``c`')
    })

    it('escapes control characters instead of emitting them raw', () => {
        expect(escapePropertyAsHogQLIdentifier('a\tb')).toEqual('"a\\tb"')
        expect(escapePropertyAsHogQLIdentifier('a\nb')).toEqual('"a\\nb"')
        expect(escapePropertyAsHogQLIdentifier('a\bb')).toEqual('"a\\bb"')
        // An embedded double quote forces the backtick branch; the control char is still escaped.
        expect(escapePropertyAsHogQLIdentifier('a"\tb')).toEqual('`a"\\tb`')
    })
})

describe('escapeDottedHogQLIdentifier', () => {
    it('leaves simple dotted identifiers unquoted', () => {
        expect(escapeDottedHogQLIdentifier('demo.orders')).toEqual('demo.orders')
    })

    it('quotes each dotted segment independently when needed', () => {
        expect(escapeDottedHogQLIdentifier('demo.order items')).toEqual('demo."order items"')
    })
})

describe('convertDataTableNodeToDataVisualizationNode', () => {
    it('preserves visible and pinned columns from legacy HogQL data table nodes', () => {
        const convertedNode = convertDataTableNodeToDataVisualizationNode({
            kind: NodeKind.DataTableNode,
            source: {
                kind: NodeKind.HogQLQuery,
                query: 'select * from events',
            },
            columns: ['event', 'timestamp', 'person_id'],
            hiddenColumns: ['person_id'],
            pinnedColumns: ['event', 'person_id'],
        } as DataTableNode)

        expect(convertedNode).toEqual({
            kind: NodeKind.DataVisualizationNode,
            source: {
                kind: NodeKind.HogQLQuery,
                query: 'select * from events',
            },
            display: ChartDisplayType.ActionsTable,
            tableSettings: {
                columns: [{ column: 'event' }, { column: 'timestamp' }],
                pinnedColumns: ['event'],
            },
        } as DataVisualizationNode)
    })

    it('preserves additional legacy table config when converting HogQL data table nodes', () => {
        const convertedNode = convertDataTableNodeToDataVisualizationNode({
            kind: NodeKind.DataTableNode,
            source: {
                kind: NodeKind.HogQLQuery,
                query: 'select * from events limit 10',
            },
            full: true,
            embedded: true,
            showReload: true,
            columns: ['event'],
        } as DataTableNode)

        expect(convertedNode).toEqual({
            kind: NodeKind.DataVisualizationNode,
            source: {
                kind: NodeKind.HogQLQuery,
                query: 'select * from events limit 10',
            },
            display: ChartDisplayType.ActionsTable,
            full: true,
            embedded: true,
            showReload: true,
            tableSettings: {
                columns: [{ column: 'event' }],
            },
        })
    })
})

describe('supportsBarValueStacking', () => {
    const breakdown = { breakdown: '$browser', breakdown_type: 'event' as const }
    const trends = (display: ChartDisplayType, withBreakdown: boolean): InsightQueryNode =>
        ({
            kind: NodeKind.TrendsQuery,
            series: [],
            trendsFilter: { display },
            ...(withBreakdown ? { breakdownFilter: breakdown } : {}),
        }) as InsightQueryNode

    it.each([
        {
            name: 'trends + bar-value + breakdown',
            query: trends(ChartDisplayType.ActionsBarValue, true),
            expected: true,
        },
        {
            name: 'trends + bar-value without breakdown',
            query: trends(ChartDisplayType.ActionsBarValue, false),
            expected: false,
        },
        {
            name: 'trends + vertical bar + breakdown',
            query: trends(ChartDisplayType.ActionsBar, true),
            expected: false,
        },
        {
            name: 'trends + line + breakdown',
            query: trends(ChartDisplayType.ActionsLineGraph, true),
            expected: false,
        },
        {
            name: 'funnels + breakdown',
            query: { kind: NodeKind.FunnelsQuery, series: [], breakdownFilter: breakdown } as InsightQueryNode,
            expected: false,
        },
        { name: 'null query', query: null, expected: false },
    ])('returns $expected for $name', ({ query, expected }) => {
        expect(supportsBarValueStacking(query)).toBe(expected)
    })
})

describe('queryVizRendersToCanvas', () => {
    const insightViz = (source: InsightQueryNode): any => ({ kind: NodeKind.InsightVizNode, source })
    const trends = (display?: ChartDisplayType): InsightQueryNode =>
        ({ kind: NodeKind.TrendsQuery, series: [], trendsFilter: display ? { display } : {} }) as InsightQueryNode

    it.each([
        { name: 'HogQL data table', query: { kind: NodeKind.DataTableNode } as any, expected: false },
        {
            name: 'SQL viz as chart',
            query: { kind: NodeKind.DataVisualizationNode, display: ChartDisplayType.ActionsLineGraph } as any,
            expected: true,
        },
        {
            name: 'SQL viz as table (no display)',
            query: { kind: NodeKind.DataVisualizationNode } as any,
            expected: false,
        },
        { name: 'trends line chart', query: insightViz(trends(ChartDisplayType.ActionsLineGraph)), expected: true },
        { name: 'trends default display', query: insightViz(trends()), expected: true },
        { name: 'trends bold number', query: insightViz(trends(ChartDisplayType.BoldNumber)), expected: false },
        { name: 'trends table', query: insightViz(trends(ChartDisplayType.ActionsTable)), expected: false },
        { name: 'trends world map', query: insightViz(trends(ChartDisplayType.WorldMap)), expected: false },
        {
            name: 'funnel steps (default)',
            query: insightViz({ kind: NodeKind.FunnelsQuery, series: [] } as InsightQueryNode),
            expected: true,
        },
        {
            name: 'funnel flow (Sankey)',
            query: insightViz({
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: { funnelVizType: FunnelVizType.Flow },
            } as InsightQueryNode),
            expected: false,
        },
        {
            name: 'funnel time to convert (table)',
            query: insightViz({
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: { funnelVizType: FunnelVizType.TimeToConvert },
            } as InsightQueryNode),
            expected: false,
        },
        {
            name: 'funnel trends (line chart)',
            query: insightViz({
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: { funnelVizType: FunnelVizType.Trends },
            } as InsightQueryNode),
            expected: true,
        },
        {
            name: 'retention',
            query: insightViz({ kind: NodeKind.RetentionQuery } as InsightQueryNode),
            expected: false,
        },
        { name: 'paths', query: insightViz({ kind: NodeKind.PathsQuery } as InsightQueryNode), expected: false },
        { name: 'null query', query: null, expected: true },
    ])('returns $expected for $name', ({ query, expected }) => {
        expect(queryVizRendersToCanvas(query)).toBe(expected)
    })
})
