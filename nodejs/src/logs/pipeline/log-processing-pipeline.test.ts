import type { LogRecord } from '~/logs/log-record-avro'

import { EMPTY_DROP_STATS, type PipelineStage, runPipelineStages } from './log-processing-pipeline'

describe('runPipelineStages', () => {
    const rec = (uuid: string): LogRecord =>
        ({
            uuid,
            body: uuid,
            service_name: 'api',
            attributes: null,
            event_name: null,
            resource_attributes: null,
        }) as LogRecord

    const dropFirst = (name: 'sampling' | 'transformations'): PipelineStage => ({
        kind: 'filter',
        name,
        run: (records) => {
            const kept = records.slice(1)
            return { kept, stats: { ...EMPTY_DROP_STATS(), recordsDropped: 1, droppedBy: name } }
        },
    })

    it('runs a mutate stage over every record before a later filter drops any', async () => {
        const seen: string[] = []
        const stages: PipelineStage[] = [
            { kind: 'mutate', name: 'stamp', run: (records) => records.forEach((r) => seen.push(r.uuid!)) },
            dropFirst('sampling'),
        ]
        const { kept, stats } = await runPipelineStages([rec('a'), rec('b'), rec('c')], stages)
        expect(seen).toEqual(['a', 'b', 'c'])
        expect(kept.map((r) => r.uuid)).toEqual(['b', 'c'])
        expect(stats.recordsDropped).toBe(1)
        expect(stats.droppedBy).toBe('sampling')
    })

    it('attributes an emptied message to the last filter that dropped, not the first', async () => {
        // Sampling drops one, then transformations drop the survivor — all-dropped is on transforms.
        const stages: PipelineStage[] = [dropFirst('sampling'), dropFirst('transformations')]
        const { kept, stats } = await runPipelineStages([rec('a'), rec('b')], stages)
        expect(kept).toHaveLength(0)
        expect(stats.recordsDropped).toBe(2)
        expect(stats.droppedBy).toBe('transformations')
    })

    it('stops running stages once every record is dropped', async () => {
        let laterRan = false
        const dropAll: PipelineStage = {
            kind: 'filter',
            name: 'sampling',
            run: (records) => ({
                kept: [],
                stats: { ...EMPTY_DROP_STATS(), recordsDropped: records.length, droppedBy: 'sampling' },
            }),
        }
        const later: PipelineStage = { kind: 'mutate', name: 'later', run: () => void (laterRan = true) }
        const { kept, stats } = await runPipelineStages([rec('a')], [dropAll, later])
        expect(kept).toHaveLength(0)
        expect(stats.droppedBy).toBe('sampling')
        expect(laterRan).toBe(false)
    })
})
