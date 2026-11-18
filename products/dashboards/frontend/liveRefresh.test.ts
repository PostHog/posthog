import { NodeKind } from '~/queries/schema/schema-general'
import { DashboardTile } from '~/types'

import { clampLiveInterval, liveExecutionClassForTile, tilesDueForLiveRefresh } from './liveRefresh'

const NOW = Date.parse('2026-11-18T12:00:00Z')
const secondsAgo = (seconds: number): string => new Date(NOW - seconds * 1000).toISOString()

const insightTile = (id: number, query: Record<string, any>, lastRefresh: string | null = null): DashboardTile =>
    ({ id, insight: { query, last_refresh: lastRefresh } }) as unknown as DashboardTile
const widgetTile = (id: number, widgetType: string): DashboardTile =>
    ({ id, widget: { id: `w${id}`, widget_type: widgetType, config: {} } }) as unknown as DashboardTile

const metricsTile = (id: number, lastRefresh: string | null): DashboardTile =>
    insightTile(id, { kind: NodeKind.MetricsQuery, clauses: [] }, lastRefresh)
const trendsTile = (id: number): DashboardTile =>
    insightTile(id, { kind: NodeKind.InsightVizNode, source: { kind: NodeKind.TrendsQuery, series: [] } }, null)

describe('liveRefresh', () => {
    it.each([
        ['a metrics insight', metricsTile(1, null), 'telemetry_metrics'],
        [
            'a metrics histogram insight',
            insightTile(1, { kind: NodeKind.MetricsHistogramQuery, clauses: [] }),
            'telemetry_metrics',
        ],
        ['a metrics table widget', widgetTile(1, 'metrics_table'), 'telemetry_metrics'],
        ['a logs list widget', widgetTile(1, 'logs_list'), 'telemetry_logs'],
        ['a trends insight', trendsTile(1), null],
        ['a session replay widget', widgetTile(1, 'session_replay_list'), null],
        ['a text tile', { id: 1 } as unknown as DashboardTile, null],
    ])('classifies %s', (_name, tile, expected) => {
        expect(liveExecutionClassForTile(tile)).toEqual(expected)
    })

    it.each([
        [5, 5],
        [60, 60],
        [7, null],
        [900, null],
        ['10', null],
        [undefined, null],
    ])('clamps a stored live interval of %p to %p', (stored, expected) => {
        expect(clampLiveInterval(stored)).toEqual(expected)
    })

    it.each([
        ['an analytics tile is never refreshed by a live tick', [trendsTile(1)], {}, {}, []],
        ['a metrics tile with no result yet is due', [metricsTile(1, null)], {}, {}, [1]],
        ['a metrics tile younger than its 30 s cache age waits', [metricsTile(1, secondsAgo(20))], {}, {}, []],
        ['a metrics tile older than its 30 s cache age is due', [metricsTile(1, secondsAgo(31))], {}, {}, [1]],
        [
            'a tile whose request is still pending is not requested again',
            [metricsTile(1, secondsAgo(31))],
            { inFlight: [1] },
            {},
            [],
        ],
        [
            'a collapsed or inactive-tab tile is not requested',
            [metricsTile(1, secondsAgo(31))],
            { hidden: [1] },
            {},
            [],
        ],
        [
            'a logs widget answered less than one interval ago waits',
            [widgetTile(2, 'logs_list')],
            {},
            { 2: NOW - 2000 },
            [],
        ],
        ['a logs widget answered one interval ago is due', [widgetTile(2, 'logs_list')], {}, { 2: NOW - 5000 }, [2]],
    ])('%s', (_name, tiles, sets: { inFlight?: number[]; hidden?: number[] }, receivedAt, expectedIds) => {
        expect(
            tilesDueForLiveRefresh({
                tiles,
                now: NOW,
                intervalSeconds: 5,
                inFlightTileIds: new Set(sets.inFlight ?? []),
                hiddenTileIds: new Set(sets.hidden ?? []),
                receivedAt,
            })
        ).toEqual(expectedIds)
    })
})
