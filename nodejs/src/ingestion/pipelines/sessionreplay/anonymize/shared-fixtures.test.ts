import fs from 'fs'
import path from 'path'
import { gzipSync, zstdDecompressSync } from 'zlib'

import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'

import { AllowLists } from './allow-lists'
import { anonymizeEvent } from './anonymize-event'
import { ScrubContext } from './config'
import { scrubText } from './text'
import { scrubUrl } from './url'

// shared fixtures to guarantee identical behaviour between implementations
const FIXTURE_DIR = path.resolve(__dirname, '../../../../../../rust/replay-anonymizer-node/tests/fixtures')

interface AllowSpec {
    text: string[]
    url: string[]
}
interface TextCase {
    name: string
    allow: AllowSpec
    input: string
    expected: string
}
interface UrlCase extends TextCase {
    collapseHost?: boolean
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
function ctxOf(allow: AllowSpec): ScrubContext {
    return { allow: new AllowLists(allow.text, allow.url) }
}

function anonymizeMessageTs(allow: AllowSpec, message: Record<string, unknown[]>): Record<string, unknown> {
    const ctx = ctxOf(allow)
    const clone = structuredClone(message) as Record<string, unknown[]>
    for (const events of Object.values(clone)) {
        if (Array.isArray(events)) {
            for (const event of events) {
                anonymizeEvent(ctx, event)
            }
        }
    }
    return clone
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

describe('anonymize shared fixtures', () => {
    const textCases = load<TextCase>('text.json')
    const urlCases = load<UrlCase>('url.json')
    const eventCases = load<EventCase>('events.json')
    const messageCases = load<MessageCase>('messages.json')

    describe('typescript scrubbers match the shared fixtures', () => {
        test.each(textCases.map((c) => [c.name, c] as const))('text: %s', (_name, c) => {
            expect(scrubText(ctxOf(c.allow), c.input).value).toEqual(c.expected)
        })

        test.each(urlCases.map((c) => [c.name, c] as const))('url: %s', (_name, c) => {
            expect(scrubUrl(ctxOf(c.allow), c.input, { collapseHost: c.collapseHost }).value).toEqual(c.expected)
        })

        test.each(eventCases.map((c) => [c.name, c] as const))('event: %s', (_name, c) => {
            const event = structuredClone(c.event)
            anonymizeEvent(ctxOf(c.allow), event)
            expect(event).toEqual(c.expected)
        })

        test.each(messageCases.map((c) => [c.name, c] as const))('message: %s', (_name, c) => {
            expect(anonymizeMessageTs(c.allow, c.message)).toEqual(c.expected)
        })
    })

    const describeAddon = rustAddon ? describe : describe.skip
    describeAddon('native rust addon matches the shared fixtures', () => {
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
                    'https://example.com/[redacted]/[redacted]/'
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
        })
    })
})
