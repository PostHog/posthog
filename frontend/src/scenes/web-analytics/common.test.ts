import { NodeKind } from '~/queries/schema/schema-general'
import { InsightLogicProps, PropertyFilterType, PropertyOperator } from '~/types'

import { TileId, WebAnalyticsTile, exactMatchOperatorFor, withPresetTag } from './common'

describe('exactMatchOperatorFor', () => {
    it.each([
        ['$pathname', PropertyFilterType.Event, false, PropertyOperator.Exact],
        ['$pathname', PropertyFilterType.Event, true, PropertyOperator.IsCleanedPathExact],
        ['$entry_pathname', PropertyFilterType.Session, true, PropertyOperator.IsCleanedPathExact],
        ['$initial_pathname', PropertyFilterType.Person, true, PropertyOperator.IsCleanedPathExact],
        ['$browser', PropertyFilterType.Event, true, PropertyOperator.Exact],
        ['$entry_utm_source', PropertyFilterType.Session, true, PropertyOperator.Exact],
    ])('%s (%s, cleaning: %s) uses %s', (key, type, doPathCleaning, expected) => {
        expect(exactMatchOperatorFor(key, type, doPathCleaning)).toBe(expected)
    })
})

describe('withPresetTag', () => {
    const insightProps = {} as InsightLogicProps
    const layout = {}

    // A tagged node must already carry tags, mirroring how every web analytics tile is
    // built with WEB_ANALYTICS_DEFAULT_QUERY_TAGS.
    const sourceNode = (): any => ({
        kind: NodeKind.WebOverviewQuery,
        properties: [],
        tags: { productKey: 'web_analytics' },
    })

    const tiles = (): WebAnalyticsTile[] => [
        {
            kind: 'query',
            tileId: TileId.OVERVIEW,
            layout,
            insightProps,
            query: { kind: NodeKind.InsightVizNode, source: sourceNode() } as any,
        },
        {
            kind: 'tabs',
            tileId: TileId.SOURCES,
            layout,
            activeTabId: 'a',
            setTabId: () => {},
            tabs: [
                {
                    id: 'a',
                    title: 'a',
                    linkText: 'a',
                    insightProps,
                    query: { kind: NodeKind.DataTableNode, source: sourceNode() } as any,
                },
            ],
        },
        {
            kind: 'section',
            tileId: TileId.GRAPHS,
            layout,
            tiles: [
                {
                    kind: 'query',
                    tileId: TileId.PATHS,
                    layout,
                    insightProps,
                    query: { kind: NodeKind.InsightVizNode, source: sourceNode() } as any,
                },
            ],
        },
        { kind: 'replay', tileId: TileId.REPLAY, layout },
    ]

    it('stamps the preset id on every query, tab, and nested tile', () => {
        const [query, tabs, section, replay] = withPresetTag(tiles(), 'abc123')

        expect((query as any).query.source.tags).toEqual({ productKey: 'web_analytics', presetId: 'abc123' })
        expect((tabs as any).tabs[0].query.source.tags.presetId).toBe('abc123')
        expect((section as any).tiles[0].query.source.tags.presetId).toBe('abc123')
        expect(replay).toEqual({ kind: 'replay', tileId: TileId.REPLAY, layout })
    })

    it('returns the same array when no preset is applied, so nothing refetches', () => {
        const input = tiles()
        expect(withPresetTag(input, null)).toBe(input)
    })
})
