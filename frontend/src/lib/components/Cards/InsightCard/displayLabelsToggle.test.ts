import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import {
    canToggleDisplayLabelsInInsightQuery,
    getDisplayLabelsToggleMode,
    isDisplayLabelsEnabledInInsightQuery,
    toggleDisplayLabelsInInsightQuery,
} from './displayLabelsToggle'

describe('displayLabelsToggle', () => {
    describe('canToggleDisplayLabelsInInsightQuery', () => {
        it('returns true for trends pie', () => {
            const query = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    trendsFilter: { display: ChartDisplayType.ActionsPie },
                },
            } as any

            expect(canToggleDisplayLabelsInInsightQuery(query)).toBe(true)
        })

        it('returns false for trends bold number', () => {
            const query = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    trendsFilter: { display: ChartDisplayType.BoldNumber },
                },
            } as any

            expect(canToggleDisplayLabelsInInsightQuery(query)).toBe(false)
        })
    })

    describe('isDisplayLabelsEnabledInInsightQuery', () => {
        it('reads trends pie label toggle', () => {
            const query = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    trendsFilter: { display: ChartDisplayType.ActionsPie, showLabelsOnSeries: true },
                },
            } as any

            expect(isDisplayLabelsEnabledInInsightQuery(query)).toBe(true)
        })

        it('reads trends line values toggle', () => {
            const query = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    trendsFilter: { display: ChartDisplayType.ActionsLineGraph, showValuesOnSeries: true },
                },
            } as any

            expect(isDisplayLabelsEnabledInInsightQuery(query)).toBe(true)
        })
    })

    describe('getDisplayLabelsToggleMode', () => {
        it('returns pie_labels for trends pie', () => {
            const query = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    trendsFilter: { display: ChartDisplayType.ActionsPie },
                },
            } as any

            expect(getDisplayLabelsToggleMode(query)).toBe('pie_labels')
        })

        it('returns series_values for trends line', () => {
            const query = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    trendsFilter: { display: ChartDisplayType.ActionsLineGraph },
                },
            } as any

            expect(getDisplayLabelsToggleMode(query)).toBe('series_values')
        })
    })

    describe('toggleDisplayLabelsInInsightQuery', () => {
        it('toggles display labels for trends pie insights', () => {
            const query = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    trendsFilter: {
                        display: ChartDisplayType.ActionsPie,
                        showLabelsOnSeries: false,
                    },
                },
            } as any

            const updatedQuery = toggleDisplayLabelsInInsightQuery(query) as any
            expect(updatedQuery.source.trendsFilter?.showLabelsOnSeries).toBe(true)
        })

        it('toggles values on series for trends line insights', () => {
            const query = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    trendsFilter: {
                        display: ChartDisplayType.ActionsLineGraph,
                        showValuesOnSeries: false,
                    },
                },
            } as any

            const updatedQuery = toggleDisplayLabelsInInsightQuery(query) as any
            expect(updatedQuery.source.trendsFilter?.showValuesOnSeries).toBe(true)
        })

        it('keeps query unchanged for trends displays without series values', () => {
            const query = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    trendsFilter: {
                        display: ChartDisplayType.BoldNumber,
                        showValuesOnSeries: false,
                    },
                },
            } as any

            const updatedQuery = toggleDisplayLabelsInInsightQuery(query)
            expect(updatedQuery).toBe(query)
        })
    })
})
