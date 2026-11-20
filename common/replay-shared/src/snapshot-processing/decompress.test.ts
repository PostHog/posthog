import { gzipSync, strFromU8, strToU8 } from 'fflate'
import { constants, zstdCompressSync } from 'node:zlib'

import { ReplayTelemetry } from '../telemetry'
import { ExpansionBudget, ExpansionBudgetExceededError, MAX_EXPANDED_FIELD_BYTES, decompressEvent } from './decompress'
import { clearThrottle } from './throttle-capturing'

const FULL_SNAPSHOT_DATA = { node: { id: 1, tag: 'div' }, initialOffset: { left: 0, top: 16 } }
const TEXTS = [{ id: 5, value: 'hello' }]

const toWire = (bytes: Uint8Array): string => strFromU8(bytes, true)
const gzipWire = (value: unknown): string => toWire(gzipSync(strToU8(JSON.stringify(value))))
// Fixtures compress via node:zlib (tests run in node); shipped code stays on decompress-only fzstd.
const zstdWire = (value: unknown): string => toWire(zstdCompressSync(strToU8(JSON.stringify(value))))
// A streaming encoder leaves the content size out of the frame header.
const zstdWireWithoutSize = (value: unknown): string =>
    toWire(
        zstdCompressSync(strToU8(JSON.stringify(value)), {
            params: { [constants.ZSTD_c_contentSizeFlag]: 0 },
        })
    )

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

    const oversizedGzip = (): string => {
        const bytes = gzipSync(strToU8(JSON.stringify(FULL_SNAPSHOT_DATA)))
        bytes.set([0xff, 0xff, 0xff, 0xff], bytes.byteLength - 4)
        return toWire(bytes)
    }
    // A single-segment frame header declaring 2^40 bytes, with no blocks after it.
    const oversizedZstd = (): string => toWire(new Uint8Array([0x28, 0xb5, 0x2f, 0xfd, 0xe0, 0, 0, 0, 0, 0, 1, 0, 0]))

    it.each([
        ['neither gzip nor zstd', (): string => 'not a compressed frame', 'neither gzip nor zstd'],
        ['gzip declaring more than the size limit', oversizedGzip, 'expanded size limit'],
        ['zstd declaring more than the size limit', oversizedZstd, 'expanded size limit'],
        [
            'zstd that declares no size and expands past the limit',
            (): string => zstdWireWithoutSize('a'.repeat(MAX_EXPANDED_FIELD_BYTES)),
            'expanded size limit',
        ],
    ])('passes the event through and reports when the payload is %s', (_label, wire: () => string, reason: string) => {
        const ev = { cv: '2024-10', type: 2, timestamp: 1, data: wire() }
        const result = decompressEvent(ev, 'session-3', telemetry)
        expect(result).toBe(ev)
        expect(telemetry.captureException).toHaveBeenCalledTimes(1)
        expect((jest.mocked(telemetry.captureException).mock.calls[0][0] as Error).message).toContain(reason)
    })

    it.each([
        ['gzip', gzipWire],
        ['zstd without a declared size', zstdWireWithoutSize],
    ])('stops at the shared budget across fields compressed as %s', (_label, wire: (value: unknown) => string) => {
        const field = wire(FULL_SNAPSHOT_DATA)
        const fieldBytes = JSON.stringify(FULL_SNAPSHOT_DATA).length
        const budget = new ExpansionBudget(fieldBytes * 2)
        const ev = { cv: '2024-10', type: 2, timestamp: 1, data: field }

        decompressEvent(ev, 'session-4', telemetry, budget)
        decompressEvent(ev, 'session-4', telemetry, budget)

        expect(() => decompressEvent(ev, 'session-4', telemetry, budget)).toThrow(ExpansionBudgetExceededError)
    })
})
