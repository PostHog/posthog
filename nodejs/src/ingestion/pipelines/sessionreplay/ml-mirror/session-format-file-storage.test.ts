import {
    SessionBatchFileStorage,
    WriteSessionData,
} from '~/ingestion/pipelines/sessionreplay/sessions/session-batch-file-storage'

import { SessionFormatFileStorage } from './session-format-file-storage'
import cases from './session-identifier-format-cases.json'

function storage(prefix: string): SessionBatchFileStorage & { buffers: Buffer[]; finish: jest.Mock } {
    const buffers: Buffer[] = []
    const finish = jest.fn().mockResolvedValue(undefined)
    return {
        buffers,
        finish,
        checkHealth: () => Promise.resolve(true),
        newBatch: () => ({
            writeSession: (data: WriteSessionData) => {
                const start = Buffer.concat(buffers).length
                buffers.push(data.buffer)
                return Promise.resolve({
                    bytesWritten: data.buffer.length,
                    url: `${prefix}?range=bytes=${start}-${start + data.buffer.length - 1}`,
                    retentionPeriodDays: null,
                })
            },
            finish,
        }),
    }
}

describe('SessionFormatFileStorage', () => {
    it('routes sessions to separate objects and byte ranges in mixed batches', async () => {
        const legacy = storage('rrweb/object')
        const raw = storage('rrweb_2/object')
        const mixed = new SessionFormatFileStorage(legacy, () => raw)
        for (let batch = 0; batch < 2; batch++) {
            const writer = mixed.newBatch()
            for (const entry of cases.cases) {
                const destination = entry.rawIdentifiers ? raw : legacy
                const prefix = entry.rawIdentifiers ? 'rrweb_2/object' : 'rrweb/object'
                const start = Buffer.concat(destination.buffers).length
                const result = await writer.writeSession({
                    buffer: Buffer.from('abc'),
                    sessionId: entry.sessionId,
                    teamId: 7,
                    retentionPeriod: '30d',
                })
                expect(result.url).toBe(`${prefix}?range=bytes=${start}-${start + 2}`)
            }
            await writer.finish()
        }
        expect(legacy.finish).toHaveBeenCalledTimes(2)
        expect(raw.finish).toHaveBeenCalledTimes(2)
        expect(raw.buffers).toHaveLength(cases.cases.filter((entry) => entry.rawIdentifiers).length * 2)
        expect(legacy.buffers).toHaveLength(cases.cases.filter((entry) => !entry.rawIdentifiers).length * 2)
    })

    it('keeps late sessions in their start month across mixed batches', async () => {
        const legacy = storage('rrweb/object')
        const september = storage('rrweb_2/2026-09/object')
        const october = storage('rrweb_2/2026-10/object')
        const writer = new SessionFormatFileStorage(legacy, (month) =>
            month === '2026-09' ? september : october
        ).newBatch()
        for (const [date, prefix] of [
            ['2026-09-30T23:59:59.999Z', '2026-09'],
            ['2026-10-01T00:00:00Z', '2026-10'],
            ['2026-09-30T23:59:59.999Z', '2026-09'],
        ]) {
            const hex = Date.parse(date).toString(16).padStart(12, '0')
            const result = await writer.writeSession({
                buffer: Buffer.from('abc'),
                teamId: 7,
                sessionId: `${hex.slice(0, 8)}-${hex.slice(8)}-7000-8000-000000000007`,
                retentionPeriod: '30d',
            })
            expect(result.url).toContain(`rrweb_2/${prefix}/`)
        }
        await writer.finish()
        expect(september.buffers).toHaveLength(2)
        expect(october.buffers).toHaveLength(1)
    })

    it('waits for both uploads before reporting a failure', async () => {
        const legacy = storage('rrweb/object')
        const raw = storage('rrweb_2/object')
        legacy.finish.mockRejectedValue(new Error('upload failed'))
        let completeRaw!: () => void
        raw.finish.mockReturnValue(
            new Promise<void>((resolve) => {
                completeRaw = resolve
            })
        )
        const writer = new SessionFormatFileStorage(legacy, () => raw).newBatch()
        for (const entry of cases.cases.slice(0, 2)) {
            await writer.writeSession({
                buffer: Buffer.from('abc'),
                sessionId: entry.sessionId,
                teamId: 7,
                retentionPeriod: '30d',
            })
        }
        const settled = jest.fn()
        const done = writer.finish().catch(settled)
        await Promise.resolve()
        expect(settled).not.toHaveBeenCalled()
        completeRaw()
        await done
        expect(settled).toHaveBeenCalledWith(new Error('upload failed'))
    })
})
