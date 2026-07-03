import fs from 'fs'
import path from 'path'

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
    })
})
