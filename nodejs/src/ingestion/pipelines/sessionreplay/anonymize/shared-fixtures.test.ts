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
const FIXTURE_DIR = path.resolve(__dirname, '../../../../../../rust/common/replay-anonymizer/tests/fixtures')

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

function load<T>(name: string): T[] {
    return parseJSON(fs.readFileSync(path.join(FIXTURE_DIR, name), 'utf8'))
}
function ctxOf(allow: AllowSpec): ScrubContext {
    return { allow: new AllowLists(allow.text, allow.url) }
}

// Try to load the native addon; it's built by turbo `^build` in CI. When it isn't (a dev who hasn't
// run `pnpm build:replay-anonymizer`), skip only the addon block — the TS parity still runs.
let rustAddon: typeof import('@posthog/replay-anonymizer') | null = null
try {
    rustAddon = require('@posthog/replay-anonymizer')
} catch {
    logger.warn('🙈', 'replay_anonymizer_addon_not_built_skipping_native_parity')
}

describe('anonymize shared fixtures', () => {
    const textCases = load<TextCase>('text.json')
    const urlCases = load<UrlCase>('url.json')
    const eventCases = load<EventCase>('events.json')

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
    })

    const describeAddon = rustAddon ? describe : describe.skip
    describeAddon('native rust addon matches the shared fixtures', () => {
        test.each(eventCases.map((c) => [c.name, c] as const))('event: %s', async (_name, c) => {
            rustAddon!.initAnonymizer(c.allow)
            const result = await rustAddon!.anonymize(JSON.stringify({ w: [c.event] }))
            expect(result.failed).toBe(false)
            const actual = result.data === null ? c.event : (parseJSON(result.data) as { w: unknown[] }).w[0]
            expect(actual).toEqual(c.expected)
        })
    })
})
