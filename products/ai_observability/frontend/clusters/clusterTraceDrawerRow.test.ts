import type { TraceWithSummary } from './clusterDetailLogic'
import { toClusterTraceDrawerRow } from './clusterTraceDrawerRow'
import type { ClusterItemInfo, TraceSummary } from './types'

function member(info: Partial<ClusterItemInfo> = {}, summary?: Partial<TraceSummary>): TraceWithSummary {
    return {
        traceId: 'item-key',
        traceInfo: {
            distance_to_centroid: 0,
            rank: 1,
            x: 0,
            y: 0,
            timestamp: '2024-01-01T00:00:00+00:00',
            trace_id: 'trace-1',
            ...info,
        },
        summary: summary && {
            traceId: 'summary-trace',
            title: '',
            flowDiagram: '',
            bullets: '',
            interestingNotes: '',
            timestamp: '',
            ...summary,
        },
    }
}

describe('toClusterTraceDrawerRow', () => {
    it.each([
        [
            'a trace opens the trace',
            'trace',
            member(),
            { traceId: 'item-key', timestamp: '2024-01-01T00:00:00.000Z', stepId: null },
        ],
        [
            'a generation opens its step in its trace',
            'generation',
            member({ generation_id: 'gen-1' }),
            { traceId: 'trace-1', timestamp: '2024-01-01T00:00:00.000Z', stepId: 'gen-1' },
        ],
        [
            'a generation with no timestamp has none',
            'generation',
            member({ timestamp: '' }),
            { traceId: 'trace-1', timestamp: null, stepId: null },
        ],
        [
            'an evaluation opens the generation it judged, never its own uuid',
            'evaluation',
            member({ trace_id: 'eval-uuid' }, { traceId: 'trace-2', generationId: 'gen-2' }),
            { traceId: 'trace-2', timestamp: null, stepId: 'gen-2' },
        ],
        ['an evaluation with no summary has no row', 'evaluation', member(), null],
        ['an evaluation whose summary has no trace has no row', 'evaluation', member({}, { traceId: '' }), null],
    ] as const)('maps %s', (_name, level, item, expected) => {
        expect(toClusterTraceDrawerRow(item, level)).toEqual(expected)
    })
})
