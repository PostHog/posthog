import { enrich, makeEvent, makeTrace } from './testFixtures'
import { toTimeline } from './toTimeline'
import { toTraceTree } from './toTraceTree'

describe('toTimeline', () => {
    it('lists each parent directly above its children, with their depth and errors, and leaves unknown latency empty', () => {
        const event = (
            id: string,
            parentId: string,
            second: number,
            latency?: number,
            error?: string
        ): ReturnType<typeof makeEvent> =>
            makeEvent({
                id,
                event: id.startsWith('gen') ? '$ai_generation' : '$ai_span',
                createdAt: `2026-09-01T10:15:0${second}.000Z`,
                properties: {
                    $ai_trace_id: 'trace-1',
                    $ai_parent_id: parentId,
                    ...(latency !== undefined ? { $ai_latency: latency } : {}),
                    ...(error !== undefined ? { $ai_error: error } : {}),
                },
            })
        const firstGeneration = event('gen-1', 'trace-1', 1, 1)
        const firstTool = event('span-1', 'gen-1', 2, undefined, 'Tool timed out')
        const secondGeneration = event('gen-2', 'trace-1', 3, 1)
        const secondTool = event('span-2', 'gen-2', 4, 0.5)
        const trace = makeTrace({ events: [firstGeneration, secondGeneration, firstTool, secondTool] })
        const tree = toTraceTree(trace, [
            enrich(firstGeneration, [enrich(firstTool)]),
            enrich(secondGeneration, [enrich(secondTool)]),
        ])

        const timeline = toTimeline(trace, tree)

        expect(timeline.rows.map((row) => [row.id, row.depth, row.durationMs, row.hasError])).toEqual([
            ['gen-1', 0, 1000, false],
            ['span-1', 1, null, true],
            ['gen-2', 0, 1000, false],
            ['span-2', 1, 500, false],
        ])
        expect(timeline.totalMs).toBeGreaterThan(0)
    })
})
