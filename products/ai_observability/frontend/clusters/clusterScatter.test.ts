import { clusterItemLabel } from './clusterScatter'
import type { ClusterScatterMeta } from './clusterScatter'
import { TraceSummary } from './types'

const summary = (overrides: Partial<TraceSummary>): TraceSummary => ({
    traceId: 'trace-1',
    title: 'Untitled',
    flowDiagram: '',
    bullets: '',
    interestingNotes: '',
    timestamp: '2025-01-05T10:00:00Z',
    ...overrides,
})

describe('clusterScatter', () => {
    describe('clusterItemLabel', () => {
        const meta: ClusterScatterMeta = { traceId: 'trace-1', generationId: 'gen-1' }

        it.each([
            ['trace', 'trace-1', 'Trace title'],
            ['generation', 'gen-1', 'Generation title'],
        ] as const)('reads %s summaries by the id navigation uses', (level, key, title) => {
            expect(clusterItemLabel(meta, level, { [key]: summary({ title }) })).toBe(title)
        })

        it('returns nothing when the summary is keyed by the other id', () => {
            expect(clusterItemLabel(meta, 'trace', { 'gen-1': summary({ title: 'x' }) })).toBeUndefined()
            expect(clusterItemLabel(meta, 'generation', { 'trace-1': summary({ title: 'x' }) })).toBeUndefined()
        })

        it('strips the verdict suffix for evaluation summaries, keyed by generationId', () => {
            expect(clusterItemLabel(meta, 'evaluation', { 'gen-1': summary({ title: 'Accuracy: PASS' }) })).toBe(
                'Accuracy'
            )
        })
    })
})
