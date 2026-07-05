import fs from 'fs'
import path from 'path'
import { gunzipSync, gzipSync } from 'zlib'

import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'

import { AllowLists } from './allow-lists'
import { anonymizeEvent } from './anonymize-event'
import { ScrubContext } from './config'
import { scrubText } from './text'
import { scrubUrl } from './url'

// Same JSON fixtures the Rust `cargo test` runs against (single source of truth). If the two
// implementations ever diverge, the assertions fail on whichever side drifted.
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
    scrubAuthority?: boolean
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

// Mirrors the Rust `anonymize_message` whole-message walk: for each window that is an array, scrub each
// event in place. This is the TS side of the full-message parity fixtures.
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

// Try to load the native addon; it's built by turbo `^build` in CI. When it isn't (a dev who hasn't
// run `pnpm build:replay-anonymizer`), skip only the addon block — the TS parity still runs. In CI the
// addon is always built, so a load failure would silently drop all native parity coverage: fail loudly
// there instead of skipping, so a broken addon can't turn the suite green with zero cross-impl checks.
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
            expect(scrubUrl(ctxOf(c.allow), c.input, { scrubAuthority: c.scrubAuthority }).value).toEqual(c.expected)
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

        // Wrap fixture events in the Kafka payload shape the addon consumes. The scrub fixtures don't
        // carry timestamps (they only pin scrub behavior), so inject them — into the input and the
        // expected side identically — since the fused parse step filters events without one.
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

        // The expected JSONL lines: the fixture's expected events with the same timestamps injected,
        // minus non-object events (the parse step filters those out).
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

        test.each(eventCases.map((c) => [c.name, c] as const))('event: %s', async (_name, c) => {
            // The addon holds one process-global allow list (set once in prod, mirroring cyclotron's
            // initManager). Re-initing per case is safe only because Jest runs this file with
            // --runInBand: cases are sequential, so no case observes another's allow list.
            rustAddon!.initAnonymizer(c.allow)
            const result = await rustAddon!.anonymizeKafkaPayload(payloadOf('w', [c.event]))
            expect(result.failed).toBe(false)
            expect(parseLines(result.lines!)).toEqual(expectedLines('w', [c.expected]))
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

        // cv-compressed events can't live in the static JSON fixtures (their payloads are raw
        // gzip bytes), and the Rust-side cv coverage never runs a payload through the addon's
        // production FFI. These cases gzip a known payload, run the whole decode/scrub/re-emit
        // path through anonymizeKafkaPayload, then decompress the output to assert the scrub —
        // the one place the native cv wire path is checked end to end.
        describe('cv-compressed events through the production entry', () => {
            // latin-1: each gzip byte is a U+00XX codepoint, matching the SDK wire format.
            const gzipLatin1 = (json: string): string => Buffer.from(gzipSync(Buffer.from(json))).toString('latin1')
            const gunzipLatin1 = (s: string): unknown => parseJSON(gunzipSync(Buffer.from(s, 'latin1')).toString())

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

            // cvZstd:false keeps the output gzip so the assertion can decode it with zlib alone;
            // the scrub semantics are format-independent (the codec only changes the re-emit leg).
            it('scrubs a cv full snapshot and re-emits a decodable payload', async () => {
                rustAddon!.initAnonymizer({ text: ['keep'], url: [] })
                const result = await rustAddon!.anonymizeKafkaPayload(payloadOf('w', [fullSnapshot]), undefined, false)
                expect(result.failed).toBe(false)
                const line = parseLines(result.lines!)[0] as [string, { data: string }]
                const decoded = gunzipLatin1(line[1].data) as { node: { childNodes: { textContent: string }[] } }
                expect(decoded.node.childNodes[0].textContent).toBe('keep ******')
            })

            it('scrubs a cv mutation sub-field and re-emits a decodable payload', async () => {
                rustAddon!.initAnonymizer({ text: ['keep'], url: [] })
                const result = await rustAddon!.anonymizeKafkaPayload(payloadOf('w', [mutation]), undefined, false)
                expect(result.failed).toBe(false)
                const line = parseLines(result.lines!)[0] as [string, { data: { texts: string } }]
                const decoded = gunzipLatin1(line[1].data.texts) as { value: string }[]
                expect(decoded[0].value).toBe('keep ******')
            })

            // The production default re-emits zstd; downstream dispatches on the magic bytes, so
            // pin that a changed payload actually carries the zstd frame magic (28 b5 2f fd).
            it('emits zstd frames by default', async () => {
                rustAddon!.initAnonymizer({ text: ['keep'], url: [] })
                const result = await rustAddon!.anonymizeKafkaPayload(payloadOf('w', [fullSnapshot]))
                expect(result.failed).toBe(false)
                const line = parseLines(result.lines!)[0] as [string, { data: string }]
                const magic = Buffer.from(line[1].data, 'latin1').subarray(0, 4)
                expect([...magic]).toEqual([0x28, 0xb5, 0x2f, 0xfd])
            })
        })
    })
})
