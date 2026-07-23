import {
    QuarantineEntry,
    activePlaywrightEntries,
    decideForTest,
    parseQuarantine,
    selectorMatches,
} from '../../../playwright/playwright.quarantine'

const TODAY = '2026-06-10'
const REPO = '/repo'

function entry(overrides: Partial<QuarantineEntry> = {}): QuarantineEntry {
    return {
        id: 'playwright/e2e/login.spec.ts',
        mode: 'run',
        reason: 'flaky',
        owner: '@web',
        issue: '',
        expires: '2026-06-20',
        ...overrides,
    }
}

// This is a JS reimplementation of core.py's contract for runner: "playwright",
// so it can drift from the Python source independently and needs its own lock.
describe('playwright.quarantine', () => {
    describe('selectorMatches', () => {
        // The space boundary is the playwright-specific rule: a ::-qualified selector
        // whose name carries spaces must still cover a nested describe/test.
        test.each<[string, string, string, boolean]>([
            ['file covers a test', 'playwright/e2e/login.spec.ts', 'playwright/e2e/login.spec.ts::A works', true],
            ['directory prefix', 'playwright/e2e', 'playwright/e2e/login.spec.ts::A works', true],
            ['describe via space', 'playwright/e2e/x.spec.ts::Auth', 'playwright/e2e/x.spec.ts::Auth logs in', true],
            [
                'exact full name',
                'playwright/e2e/x.spec.ts::Auth logs in',
                'playwright/e2e/x.spec.ts::Auth logs in',
                true,
            ],
            ['partial word', 'playwright/e2e/x.spec.ts::Au', 'playwright/e2e/x.spec.ts::Auth logs in', false],
            ['product selector', 'product:batch-exports', 'products/batch_exports/frontend/e2e/x.spec.ts::A', true],
            ['product mismatch', 'product:batch-exports', 'playwright/e2e/x.spec.ts::A', false],
        ])('%s', (_label, selector, testId, expected) => {
            expect(selectorMatches(selector, testId)).toBe(expected)
        })
    })

    describe('activePlaywrightEntries', () => {
        test('keeps only unexpired playwright entries', () => {
            const raw = [
                { id: 'a', runner: 'playwright', expires: '2026-06-20' },
                { id: 'b', runner: 'playwright', expires: '2026-06-01' }, // expired
                { id: 'c', expires: '2026-06-20' }, // defaults to pytest
                { id: 'd', runner: 'jest', expires: '2026-06-20' },
                { id: 'e', runner: 'playwright', mode: 'pause', expires: '2026-06-20' }, // invalid mode dropped
                { id: 'f', runner: 'playwright', mode: 'skip', expires: '2026-06-20' },
            ]
            expect(activePlaywrightEntries(raw, TODAY).map((e) => e.id)).toEqual(['a', 'f'])
        })

        // A malformed expires must drop the entry (fail-safe), mirroring core.py's
        // date.fromisoformat rejection. Without the ISO guard, the raw string compare
        // sorts these after TODAY and would mask the test past its expiry forever.
        test.each<[string, string]>([
            ['non-zero-padded', '2026-9-05'],
            ['non-date text', 'soon'],
            ['impossible month', '2026-13-05'],
        ])('drops an entry whose expires is %s', (_label, expires) => {
            expect(activePlaywrightEntries([{ id: 'x', runner: 'playwright', expires }], TODAY)).toEqual([])
        })
    })

    describe('decideForTest', () => {
        // The genuinely new logic: assemble the repo-relative id from an absolute file +
        // name parts, then pick the most specific match. Both the fixture and reporter call this.
        const entries = [
            entry({ id: 'playwright/e2e', mode: 'run' }),
            entry({ id: 'playwright/e2e/login.spec.ts::Login', mode: 'skip', expires: '2026-06-25' }),
        ]

        test('the most specific selector wins so a narrow skip overrides a broad run', () => {
            const decision = decideForTest(
                entries,
                '/repo/playwright/e2e/login.spec.ts',
                ['Login', 'redirects home'],
                REPO
            )
            expect(decision?.mode).toBe('skip')
            expect(decision?.label).toContain('quarantined until 2026-06-25')
            expect(decision?.label).toContain('flaky')
        })

        test('a test only covered by the broad entry runs', () => {
            const decision = decideForTest(entries, '/repo/playwright/e2e/signup.spec.ts', ['Signup', 'works'], REPO)
            expect(decision?.mode).toBe('run')
        })

        test('returns null when nothing matches', () => {
            expect(decideForTest(entries, '/repo/products/x/frontend/e2e/x.spec.ts', ['A'], REPO)).toBeNull()
        })
    })

    describe('parseQuarantine', () => {
        test('reads v1 entries and drops ones without an id', () => {
            const text = JSON.stringify({
                version: 1,
                entries: [{ id: 'playwright/e2e/x.spec.ts', runner: 'playwright' }, { runner: 'playwright' }],
            })
            expect(parseQuarantine(text).map((e) => e.id)).toEqual(['playwright/e2e/x.spec.ts'])
        })

        test.each<[string, string]>([
            ['unsupported version', JSON.stringify({ version: 2, entries: [{ id: 'a' }] })],
            ['entries not a list', JSON.stringify({ version: 1, entries: {} })],
        ])('returns [] for %s', (_label, text) => {
            expect(parseQuarantine(text)).toEqual([])
        })
    })
})
