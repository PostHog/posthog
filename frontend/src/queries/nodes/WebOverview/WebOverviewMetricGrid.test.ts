import { NodeKind } from '~/queries/schema/schema-general'
import { BaseMathType, PropertyMathType, TrendResult } from '~/types'

import { buildWebOverviewSparklineSeries, mapSparklineSeriesByKey } from './WebOverviewMetricGrid'

describe('WebOverviewMetricGrid helpers', () => {
    describe('buildWebOverviewSparklineSeries', () => {
        it('builds the five core metrics against $pageview by default', () => {
            const defs = buildWebOverviewSparklineSeries(false, null)
            expect(defs.map((d) => d.key)).toEqual(['visitors', 'views', 'sessions', 'session duration', 'bounce rate'])
            expect(
                defs.every((d) => d.node.kind === NodeKind.EventsNode && (d.node as any).event === '$pageview')
            ).toBe(true)
            expect((defs[0].node as any).math).toBe(BaseMathType.UniqueUsers)
            expect((defs[1].node as any).math).toBe(BaseMathType.TotalCount)
            expect((defs[2].node as any).math).toBe(BaseMathType.UniqueSessions)
            expect((defs[3].node as any).math).toBe(PropertyMathType.Average)
            expect((defs[3].node as any).math_property).toBe('$session_duration')
            expect((defs[4].node as any).math_property).toBe('$is_bounce')
        })

        it('uses $screen events in mobile mode', () => {
            const defs = buildWebOverviewSparklineSeries(true, null)
            expect(defs.every((d) => (d.node as any).event === '$screen')).toBe(true)
        })

        it('appends action-based conversion series when the goal is an action', () => {
            const defs = buildWebOverviewSparklineSeries(false, { actionId: 42 })
            const conversions = defs.filter((d) => d.key.endsWith('conversions'))
            expect(conversions.map((d) => d.key)).toEqual(['unique conversions', 'total conversions'])
            expect(conversions.every((d) => d.node.kind === NodeKind.ActionsNode && (d.node as any).id === 42)).toBe(
                true
            )
            expect((conversions[0].node as any).math).toBe(BaseMathType.UniqueUsers)
            expect((conversions[1].node as any).math).toBe(BaseMathType.TotalCount)
        })

        it('appends custom-event conversion series when the goal is a custom event', () => {
            const defs = buildWebOverviewSparklineSeries(false, { customEventName: 'signup' })
            const conversions = defs.filter((d) => d.key.endsWith('conversions'))
            expect(
                conversions.every((d) => d.node.kind === NodeKind.EventsNode && (d.node as any).event === 'signup')
            ).toBe(true)
        })
    })

    describe('mapSparklineSeriesByKey', () => {
        const defs = buildWebOverviewSparklineSeries(false, null)

        it('returns an empty map when there are no results', () => {
            expect(mapSparklineSeriesByKey(defs, undefined)).toEqual({})
        })

        it('maps results to keys by series order', () => {
            const results = [{ data: [1, 2, 3] }, { data: [4, 5, 6] }] as TrendResult[]
            const byKey = mapSparklineSeriesByKey(defs, results)
            expect(byKey['visitors']).toEqual([1, 2, 3])
            expect(byKey['views']).toEqual([4, 5, 6])
            expect(byKey['sessions']).toBeUndefined()
        })

        it('skips entries whose data is not an array', () => {
            const results = [{ data: undefined }, { data: [7, 8] }] as unknown as TrendResult[]
            const byKey = mapSparklineSeriesByKey(defs, results)
            expect(byKey['visitors']).toBeUndefined()
            expect(byKey['views']).toEqual([7, 8])
        })
    })
})
