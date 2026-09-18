import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { normalizeUrlQuery } from './normalizeUrlQuery'

const trendsQuery = (source: Record<string, any>): Record<string, any> => ({
    kind: NodeKind.InsightVizNode,
    source: { kind: NodeKind.TrendsQuery, series: [{ kind: NodeKind.EventsNode, event: '$pageview' }], ...source },
})

describe('normalizeUrlQuery', () => {
    it.each([
        ['Line', ChartDisplayType.ActionsLineGraph],
        ['ActionsLine', ChartDisplayType.ActionsLineGraph],
        ['Table', ChartDisplayType.ActionsTable],
        ['Pie', ChartDisplayType.ActionsPie],
        ['Number', ChartDisplayType.BoldNumber],
        ['actionsbar', ChartDisplayType.ActionsBar],
    ])('maps the short display value %s to %s', (display, expected) => {
        const { query, repairs } = normalizeUrlQuery(trendsQuery({ trendsFilter: { display } }))

        expect((query as any).source.trendsFilter.display).toEqual(expected)
        expect(repairs).toEqual(['display'])
    })

    it('drops a display value with no equivalent chart', () => {
        const { query, repairs } = normalizeUrlQuery(trendsQuery({ trendsFilter: { display: 'Sankey' } }))

        expect((query as any).source.trendsFilter).toEqual({})
        expect(repairs).toEqual(['display'])
    })

    it('keeps a valid display value untouched', () => {
        const { query, repairs } = normalizeUrlQuery(
            trendsQuery({ trendsFilter: { display: ChartDisplayType.WorldMap } })
        )

        expect((query as any).source.trendsFilter.display).toEqual(ChartDisplayType.WorldMap)
        expect(repairs).toEqual([])
    })

    it('repairs the display a DataVisualizationNode holds itself', () => {
        const { query, repairs } = normalizeUrlQuery({
            kind: NodeKind.DataVisualizationNode,
            source: { kind: NodeKind.HogQLQuery, query: 'select 1' },
            display: 'Table',
        })

        expect((query as any).display).toEqual(ChartDisplayType.ActionsTable)
        expect(repairs).toEqual(['display'])
    })

    it('moves breakdown keys off a series entry onto the source', () => {
        const { query, repairs } = normalizeUrlQuery(
            trendsQuery({
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: '$pageview',
                        breakdown: '$browser',
                        breakdown_type: 'event',
                    },
                ],
            })
        )

        expect((query as any).source.series).toEqual([{ kind: NodeKind.EventsNode, event: '$pageview' }])
        expect((query as any).source.breakdownFilter).toEqual({ breakdown: '$browser', breakdown_type: 'event' })
        expect(repairs).toEqual(['series_breakdown'])
    })

    it('keeps the breakdown the source already declares', () => {
        const { query } = normalizeUrlQuery(
            trendsQuery({
                series: [{ kind: NodeKind.EventsNode, event: '$pageview', breakdown: '$browser' }],
                breakdownFilter: { breakdown: '$os', breakdown_type: 'event' },
            })
        )

        expect((query as any).source.breakdownFilter).toEqual({ breakdown: '$os', breakdown_type: 'event' })
    })

    it('leaves a series breakdown alone on a kind without breakdownFilter', () => {
        const { query, repairs } = normalizeUrlQuery({
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.LifecycleQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview', breakdown: '$browser' }],
            },
        })

        expect((query as any).source.breakdownFilter).toBeUndefined()
        expect(repairs).toEqual([])
    })

    it.each([[null], [undefined], ['a string'], [5], [{ source: {} }]])(
        'reports %p as not runnable',
        (notAQueryNode) => {
            expect(normalizeUrlQuery(notAQueryNode)).toEqual({ query: null, repairs: [] })
        }
    )
})
