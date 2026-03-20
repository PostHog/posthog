import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import {
    canToggleDisplayLabelsInInsightQuery,
    getDisplayLabelsToggleText,
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

        it('returns false for funnels steps visualization', () => {
            const query = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.FunnelsQuery,
                    funnelsFilter: { funnelVizType: 'steps' },
                },
            } as any

            expect(canToggleDisplayLabelsInInsightQuery(query)).toBe(false)
        })

        it('returns true for funnels trends visualization', () => {
            const query = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.FunnelsQuery,
                    funnelsFilter: { funnelVizType: 'trends' },
                },
            } as any

            expect(canToggleDisplayLabelsInInsightQuery(query)).toBe(true)
        })

        it('returns true for lifecycle insights', () => {
            const query = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.LifecycleQuery,
                },
            } as any

            expect(canToggleDisplayLabelsInInsightQuery(query)).toBe(true)
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

    describe('getDisplayLabelsToggleText', () => {
        it('returns labels wording for pie insights', () => {
            const hiddenLabelsQuery = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    trendsFilter: { display: ChartDisplayType.ActionsPie, showLabelsOnSeries: false },
                },
            } as any

            const shownLabelsQuery = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    trendsFilter: { display: ChartDisplayType.ActionsPie, showLabelsOnSeries: true },
                },
            } as any

            expect(getDisplayLabelsToggleText(hiddenLabelsQuery)).toBe('Show labels on series')
            expect(getDisplayLabelsToggleText(shownLabelsQuery)).toBe('Hide labels on series')
        })

        it('returns values wording for non-pie insights', () => {
            const hiddenValuesQuery = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    trendsFilter: { display: ChartDisplayType.ActionsLineGraph, showValuesOnSeries: false },
                },
            } as any

            const shownValuesQuery = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    trendsFilter: { display: ChartDisplayType.ActionsLineGraph, showValuesOnSeries: true },
                },
            } as any

            expect(getDisplayLabelsToggleText(hiddenValuesQuery)).toBe('Show values on series')
            expect(getDisplayLabelsToggleText(shownValuesQuery)).toBe('Hide values on series')
        })
    })

    describe('toggleDisplayLabelsInInsightQuery', () => {
        it.each([
            {
                kind: NodeKind.TrendsQuery,
                filter: 'trendsFilter',
                display: ChartDisplayType.ActionsLineGraph,
                field: 'showValuesOnSeries',
            },
            {
                kind: NodeKind.TrendsQuery,
                filter: 'trendsFilter',
                display: ChartDisplayType.ActionsPie,
                field: 'showLabelsOnSeries',
            },
            {
                kind: NodeKind.StickinessQuery,
                filter: 'stickinessFilter',
                display: ChartDisplayType.ActionsLineGraph,
                field: 'showValuesOnSeries',
            },
            {
                kind: NodeKind.FunnelsQuery,
                filter: 'funnelsFilter',
                field: 'showValuesOnSeries',
            },
            {
                kind: NodeKind.LifecycleQuery,
                filter: 'lifecycleFilter',
                field: 'showValuesOnSeries',
            },
        ])('toggles $field for $kind', ({ kind, filter, display, field }) => {
            const makeQuery = (enabled: boolean): any => ({
                kind: NodeKind.InsightVizNode,
                source: {
                    kind,
                    [filter]: {
                        ...(display ? { display } : {}),
                        [field]: enabled,
                    },
                },
            })

            const enabledQuery = toggleDisplayLabelsInInsightQuery(makeQuery(false)) as any
            expect(enabledQuery.source[filter]?.[field]).toBe(true)

            const disabledQuery = toggleDisplayLabelsInInsightQuery(makeQuery(true)) as any
            expect(disabledQuery.source[filter]?.[field]).toBe(false)
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
