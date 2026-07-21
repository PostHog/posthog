import { gzipSync, strFromU8, strToU8 } from 'fflate'
import { zstdCompressSync } from 'node:zlib'

import { ReplayTelemetry } from '../telemetry'
import { decompressEvent } from './decompress'
import { clearThrottle } from './throttle-capturing'

const FULL_SNAPSHOT_DATA = { node: { id: 1, tag: 'div' }, initialOffset: { left: 0, top: 16 } }
const TEXTS = [{ id: 5, value: 'hello' }]

const toWire = (bytes: Uint8Array): string => strFromU8(bytes, true)
const gzipWire = (value: unknown): string => toWire(gzipSync(strToU8(JSON.stringify(value))))
// Fixtures compress via node:zlib (tests run in node); shipped code stays on decompress-only fzstd.
const zstdWire = (value: unknown): string => toWire(zstdCompressSync(strToU8(JSON.stringify(value))))

describe('decompressEvent', () => {
    let telemetry: ReplayTelemetry

    beforeEach(() => {
        clearThrottle()
        telemetry = { capture: jest.fn(), captureException: jest.fn() }
    })

    it.each([
        ['gzip (SDK capture format)', gzipWire(FULL_SNAPSHOT_DATA)],
        ['zstd (ml-mirror native anonymizer format)', zstdWire(FULL_SNAPSHOT_DATA)],
    ])('decompresses a full snapshot compressed as %s', (_label: string, wire: string) => {
        const ev = { cv: '2024-10', type: 2, timestamp: 1, data: wire }
        const result = decompressEvent(ev, 'session-1', telemetry) as any
        expect(result.data).toEqual(FULL_SNAPSHOT_DATA)
        expect(telemetry.captureException).not.toHaveBeenCalled()
    })

    it('decompresses a mutation mixing zstd and gzip fields in one event', () => {
        // The anonymizer re-emits only the fields it scrubs, so post-scrub events carry zstd
        // `texts`/`adds` next to untouched gzip `removes`/`attributes`.
        const ev = {
            cv: '2024-10',
            type: 3,
            timestamp: 1,
            data: {
                source: 0,
                texts: zstdWire(TEXTS),
                adds: zstdWire([]),
                attributes: gzipWire([{ id: 9, attributes: { class: 'a' } }]),
                removes: gzipWire([{ parentId: 1, id: 2 }]),
            },
        }
        const result = decompressEvent(ev, 'session-2', telemetry) as any
        expect(result.data).toEqual({
            source: 0,
            texts: TEXTS,
            adds: [],
            attributes: [{ id: 9, attributes: { class: 'a' } }],
            removes: [{ parentId: 1, id: 2 }],
        })
        expect(telemetry.captureException).not.toHaveBeenCalled()
    })

    it('passes the event through and reports when the payload is neither gzip nor zstd', () => {
        const ev = { cv: '2024-10', type: 2, timestamp: 1, data: 'not a compressed frame' }
        const result = decompressEvent(ev, 'session-3', telemetry)
        expect(result).toBe(ev)
        expect(telemetry.captureException).toHaveBeenCalledTimes(1)
    })
})
