import fs from 'fs'
import path from 'path'
import { gzipSync, zstdDecompressSync } from 'zlib'

import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'
import {
    hashImageBytes,
    imageRef,
    isImageRef,
    parseImageRef,
} from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub/content-ref'

// Shared fixtures pin the addon's behavior through the FFI; the pure-Rust side of the same
// fixtures is covered by rust/replay-anonymizer/tests/parity.rs.
const FIXTURE_DIR = path.resolve(__dirname, '../../../../../../rust/replay-anonymizer/tests/fixtures')

interface AllowSpec {
    text: string[]
    url: string[]
}
interface EventCase {
    name: string
    allow: AllowSpec
    event: Record<string, unknown>
    expected: Record<string, unknown>
}
interface MessageCase {
    name: string
    allow: AllowSpec
    message: Record<string, unknown[]>
    expected: Record<string, unknown>
}

function load<T>(name: string): T[] {
    return parseJSON(fs.readFileSync(path.join(FIXTURE_DIR, name), 'utf8'))
}

let rustAddon: typeof import('@posthog/replay-anonymizer') | null = null
try {
    rustAddon = require('@posthog/replay-anonymizer')
} catch (e) {
    if (process.env.CI) {
        throw new Error(`replay-anonymizer addon failed to load; native parity cannot run in CI: ${String(e)}`)
    }
    logger.warn('🙈', 'replay_anonymizer_addon_not_built_skipping_native_parity')
}

const describeAddon = rustAddon ? describe : describe.skip
describeAddon('native rust addon matches the shared fixtures', () => {
    const eventCases = load<EventCase>('events.json')
    const messageCases = load<MessageCase>('messages.json')

    const TS0 = 1_700_000_000_000

    // Wrap fixture events in the Kafka payload shape
    function payloadOf(windowId: string, events: unknown[]): Buffer {
        const items = structuredClone(events)
        items.forEach((ev, i) => {
            if (isRecord(ev)) {
                ev.timestamp ??= TS0 + i
            }
        })
        const inner = JSON.stringify({
            event: '$snapshot_items',
            properties: { $snapshot_items: items, $session_id: 's-1', $window_id: windowId },
        })
        return Buffer.from(JSON.stringify({ distinct_id: 'd-1', data: inner }))
    }

    function isRecord(v: unknown): v is Record<string, unknown> {
        return typeof v === 'object' && v !== null && !Array.isArray(v)
    }

    function expectedLines(windowId: string, expected: unknown[]): unknown[] {
        const events = structuredClone(expected)
        events.forEach((ev, i) => {
            if (isRecord(ev)) {
                ev.timestamp ??= TS0 + i
            }
        })
        return events.filter(isRecord).map((ev) => [windowId, ev])
    }

    function parseLines(lines: Buffer): unknown[] {
        return lines
            .toString()
            .split('\n')
            .filter((l) => l.length > 0)
            .map((l) => parseJSON(l))
    }

    describe('events', () => {
        test.each(eventCases.map((c) => [c.name, c] as const))('event: %s', async (_name, c) => {
            // --runInBand is required to ensure cases are sequential
            rustAddon!.initAnonymizer(c.allow)
            const result = await rustAddon!.anonymizeKafkaPayload(payloadOf('w', [c.event]))
            expect(result.failed).toBe(false)
            expect(parseLines(result.lines!)).toEqual(expectedLines('w', [c.expected]))
        })
    })

    test.each(messageCases.map((c) => [c.name, c] as const))('message: %s', async (_name, c) => {
        rustAddon!.initAnonymizer(c.allow)
        for (const [windowId, events] of Object.entries(c.message)) {
            const expected = expectedLines(windowId, (c.expected as Record<string, unknown[]>)[windowId])
            const result = await rustAddon!.anonymizeKafkaPayload(payloadOf(windowId, events))
            if (expected.length === 0) {
                // A window with only invalid events: the fused step drops the whole message.
                expect(result.failed).toBe(true)
                expect(result.reason).toBe('message_contained_no_valid_rrweb_events')
                continue
            }
            expect(result.failed).toBe(false)
            expect(parseLines(result.lines!)).toEqual(expected)
        }
    })

    // fixtures are plain text, convert to gzip bytes for this test
    describe('cv-compressed events through the production entry', () => {
        // latin-1: each compressed byte is a U+00XX codepoint, matching the SDK wire format.
        const gzipLatin1 = (json: string): string => Buffer.from(gzipSync(Buffer.from(json))).toString('latin1')
        const unzstdLatin1 = (s: string): unknown => {
            const raw = Buffer.from(s, 'latin1')
            // Magic-byte dispatch is the loader contract; pin the zstd frame magic on decode.
            expect([...raw.subarray(0, 4)]).toEqual([0x28, 0xb5, 0x2f, 0xfd])
            return parseJSON(zstdDecompressSync(raw).toString())
        }

        const fullSnapshot = {
            type: 2,
            cv: '2024-10',
            data: gzipLatin1(
                JSON.stringify({
                    node: { type: 0, id: 1, childNodes: [{ type: 3, id: 5, textContent: 'keep secret' }] },
                    initialOffset: { top: 0, left: 0 },
                })
            ),
        }
        const mutation = {
            type: 3,
            cv: '2024-10',
            data: { source: 0, texts: gzipLatin1(JSON.stringify([{ id: 5, value: 'keep secret' }])) },
        }

        it('scrubs a cv full snapshot and re-emits a decodable zstd payload', async () => {
            rustAddon!.initAnonymizer({ text: ['keep'], url: [] })
            const result = await rustAddon!.anonymizeKafkaPayload(payloadOf('w', [fullSnapshot]))
            expect(result.failed).toBe(false)
            const line = parseLines(result.lines!)[0] as [string, { data: string }]
            const decoded = unzstdLatin1(line[1].data) as { node: { childNodes: { textContent: string }[] } }
            expect(decoded.node.childNodes[0].textContent).toBe('keep ******')
        })

        it('media-scrubs an rr_src attribute inside a cv mutation sub-field', async () => {
            const attrMutation = {
                type: 3,
                cv: '2024-10',
                data: {
                    source: 0,
                    attributes: gzipLatin1(
                        JSON.stringify([
                            {
                                id: 7,
                                attributes: {
                                    rr_src: 'https://widget.example-vendor.co/v2/app/?refreshToken=FakeRefreshTok3nValue000',
                                },
                            },
                        ])
                    ),
                },
            }
            rustAddon!.initAnonymizer({ text: [], url: [] })
            const result = await rustAddon!.anonymizeKafkaPayload(payloadOf('w', [attrMutation]))
            expect(result.failed).toBe(false)
            const line = parseLines(result.lines!)[0] as [string, { data: { attributes: string } }]
            const decoded = unzstdLatin1(line[1].data.attributes) as { attributes: Record<string, string> }[]
            expect(decoded[0].attributes.rr_src).toMatch(/^data:image\/svg\+xml/)
            expect(decoded[0].attributes['data-anon-original-rr_src']).toBe(
                'https://widget.example-vendor.co/[redacted]/[redacted]/'
            )
        })

        it('scrubs a cv mutation sub-field and re-emits a decodable zstd payload', async () => {
            rustAddon!.initAnonymizer({ text: ['keep'], url: [] })
            const result = await rustAddon!.anonymizeKafkaPayload(payloadOf('w', [mutation]))
            expect(result.failed).toBe(false)
            const line = parseLines(result.lines!)[0] as [string, { data: { texts: string } }]
            const decoded = unzstdLatin1(line[1].data.texts) as { value: string }[]
            expect(decoded[0].value).toBe('keep ******')
        })

        it('reports ordered phase timings with cv op totals on success', async () => {
            rustAddon!.initAnonymizer({ text: ['keep'], url: [] })
            const result = await rustAddon!.anonymizeKafkaPayload(payloadOf('w', [fullSnapshot]))
            expect(result.failed).toBe(false)
            const t = result.timings!
            expect(t.taskStartNs).not.toBeNull()
            expect(t.decompressStartNs).toBeGreaterThanOrEqual(t.taskStartNs!)
            expect(t.decompressEndNs).toBeGreaterThanOrEqual(t.decompressStartNs!)
            expect(t.scrubStartNs).toBeGreaterThanOrEqual(t.decompressEndNs!)
            expect(t.scrubEndNs).toBeGreaterThanOrEqual(t.scrubStartNs!)
            // The cv full snapshot forces at least one timed de/recompression op.
            expect(t.cvCount).toBeGreaterThanOrEqual(1)
            expect(t.lastOp).toBe('done')
        })

        it('still reports timings when the payload fails, naming the phase that died', async () => {
            rustAddon!.initAnonymizer({ text: [], url: [] })
            // Gzip magic bytes followed by garbage: decompression starts, then fails.
            const result = await rustAddon!.anonymizeKafkaPayload(Buffer.from([0x1f, 0x8b, 0x08, 0x00, 0xde, 0xad]))
            expect(result.failed).toBe(true)
            const t = result.timings!
            expect(t.decompressStartNs).not.toBeNull()
            expect(t.scrubStartNs).toBeNull()
            expect(t.lastOp).toBe('decompress')
        })
    })
})

describe('image content hash matches the shared fixtures', () => {
    // Pins hashImageBytes to the Rust collector's hash (tests/parity.rs runs the same fixture):
    // a divergence makes the scrub consumer drop every produced image as a key/bytes mismatch.
    interface HashCase {
        name: string
        bytesBase64: string
        hash: string
    }
    test.each(load<HashCase>('image-hash.json').map((c) => [c.name, c] as const))('hash: %s', (_name, c) => {
        expect(hashImageBytes(Buffer.from(c.bytesBase64, 'base64'))).toBe(c.hash)
    })
})

describeAddon('native image collection', () => {
    // A 16x16 PNG; any valid raster image works, the assertions only rely on byte identity.
    const PNG_B64 =
        'iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAACXBIWXMAAAPoAAAD6AG1e1JrAAAAJUlEQVQokWN4plEBRyInbOAIlzjDINRAjCJk8cGoYRAG60iMBwA8H08Qor0ygQAAAABJRU5ErkJggg=='
    const PSEUDO_TEAM = '0123456789abcdef0123456789abcdef'

    function imagePayload(): Buffer {
        const inner = JSON.stringify({
            event: '$snapshot_items',
            properties: {
                $snapshot_items: [
                    {
                        type: 2,
                        timestamp: 1_700_000_000_000,
                        data: {
                            node: {
                                type: 0,
                                childNodes: [
                                    {
                                        type: 2,
                                        tagName: 'img',
                                        attributes: { src: `data:image/png;base64,${PNG_B64}` },
                                        childNodes: [],
                                    },
                                ],
                            },
                            initialOffset: { top: 0, left: 0 },
                        },
                    },
                ],
                $session_id: 's-1',
                $window_id: 'w',
            },
        })
        return Buffer.from(JSON.stringify({ distinct_id: 'd-1', data: inner }))
    }

    it('replaces the image with a consumer-parseable ref and returns the original bytes', async () => {
        rustAddon!.initAnonymizer({ text: [], url: [] })
        const result = await rustAddon!.anonymizeKafkaPayload(imagePayload(), undefined, undefined, PSEUDO_TEAM)
        expect(result.failed).toBe(false)

        const png = Buffer.from(PNG_B64, 'base64')
        const expectedRef = imageRef(PSEUDO_TEAM, hashImageBytes(png))
        expect(isImageRef(expectedRef)).toBe(true)
        expect(result.lines!.toString()).toContain(expectedRef)
        expect(result.lines!.toString()).not.toContain(PNG_B64)

        const meta = parseJSON(result.meta!) as { images?: { hash: string; offset: number; len: number }[] }
        expect(meta.images).toHaveLength(1)
        const entry = meta.images![0]
        const bytes = result.images!.subarray(entry.offset, entry.offset + entry.len)
        expect(Buffer.from(bytes)).toEqual(png)
        // The consumer's own validation of the produced record must hold.
        expect(hashImageBytes(Buffer.from(bytes))).toBe(entry.hash)
        expect(parseImageRef(expectedRef)).toEqual({ pseudoTeam: PSEUDO_TEAM, hash: entry.hash })
    })

    it('collects nothing without a pseudoTeam and blurs inline instead', async () => {
        rustAddon!.initAnonymizer({ text: [], url: [] })
        const result = await rustAddon!.anonymizeKafkaPayload(imagePayload())
        expect(result.failed).toBe(false)
        expect(result.images).toBeNull()
        expect(result.lines!.toString()).not.toContain(PNG_B64)
        expect(result.lines!.toString()).not.toContain('image:')
    })
})
