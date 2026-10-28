import type { LogRecord } from '~/logs/log-record-avro'

import { EMPTY_STAGE_DROP_STATS, type PipelineStage, runPipelineStages } from './log-processing-pipeline'

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

    const dropFirst = (name: 'sampling' | 'transformations' | 'retention_expired'): PipelineStage => ({
        kind: 'filter',
        name,
        run: (records) => {
            const kept = records.slice(1)
            return { kept, stats: { ...EMPTY_STAGE_DROP_STATS(), recordsDropped: 1 } }
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

    it('measures the billing pro-rate total over the whole batch when a later filter drops after an earlier one', async () => {
        // Each record's content is its one-byte body. The transform drops one row before the expiry
        // filter runs, so a total measured by that filter would cover two rows instead of three.
        const stages: PipelineStage[] = [dropFirst('transformations'), dropFirst('retention_expired')]
        const { stats } = await runPipelineStages([rec('a'), rec('b'), rec('c')], stages)
        expect(stats.contentBytesTotal).toBe(3)
        expect(Object.fromEntries(stats.recordsDroppedByStage)).toEqual({ transformations: 1, retention_expired: 1 })
    })

    it.each([
        {
            name: 'a surviving row that carries its content in resource attributes',
            records: [
                { uuid: 'expired', body: 'x', resource_attributes: null },
                { uuid: 'fresh', body: '', resource_attributes: { blob: 'r'.repeat(65_536) } },
            ],
            minShare: 0,
            maxShare: 0.001,
        },
        {
            name: 'many dropped rows that share one large resource',
            records: [
                ...Array.from({ length: 1000 }, (_, i) => ({
                    uuid: `expired-${i}`,
                    body: 'x',
                    resource_attributes: { blob: 'r'.repeat(65_536) },
                })),
                { uuid: 'fresh', body: 'f'.repeat(65_536), resource_attributes: null },
            ],
            minShare: 0.45,
            maxShare: 0.55,
        },
    ])('credits only the share of the request that was dropped: $name', async ({ records, minShare, maxShare }) => {
        const dropExpired: PipelineStage = {
            kind: 'filter',
            name: 'retention_expired',
            run: (rows, batch) => {
                const stats = EMPTY_STAGE_DROP_STATS()
                const kept = rows.filter((r) => !r.uuid!.startsWith('expired'))
                for (const r of rows.filter((r) => r.uuid!.startsWith('expired'))) {
                    stats.recordsDropped++
                    stats.contentBytesDropped += batch.contentBytesOf(r)
                }
                return { kept, stats }
            },
        }
        const rows = records.map((r) => ({ ...rec(r.uuid), ...r }) as LogRecord)
        const { stats } = await runPipelineStages(rows, [dropExpired])
        const share = stats.contentBytesDropped / stats.contentBytesTotal
        expect(share).toBeGreaterThanOrEqual(minShare)
        expect(share).toBeLessThanOrEqual(maxShare)
    })

    it('stops running stages once every record is dropped', async () => {
        let laterRan = false
        const dropAll: PipelineStage = {
            kind: 'filter',
            name: 'sampling',
            run: (records) => ({
                kept: [],
                stats: { ...EMPTY_STAGE_DROP_STATS(), recordsDropped: records.length },
            }),
        }
        const later: PipelineStage = { kind: 'mutate', name: 'later', run: () => void (laterRan = true) }
        const { kept, stats } = await runPipelineStages([rec('a')], [dropAll, later])
        expect(kept).toHaveLength(0)
        expect(stats.droppedBy).toBe('sampling')
        expect(laterRan).toBe(false)
    })
})
