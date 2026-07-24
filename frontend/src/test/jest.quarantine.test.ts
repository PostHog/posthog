import { spawnSync } from 'child_process'
import * as fs from 'fs'
import * as os from 'os'
import * as path from 'path'

import {
    activeJestEntries,
    findMatch,
    parseQuarantine,
    productPathPrefix,
    QuarantineEntry,
    repoRelativePath,
    selectorMatches,
} from '../../jest.quarantine'

const TODAY = '2026-06-10'
const REPO_ROOT = path.resolve(__dirname, '../../..')
const FRONTEND_DIR = path.join(REPO_ROOT, 'frontend')
const RUNTIME_FIXTURE_ID = 'frontend/src/test/jest.quarantine.runtime.fixture.ts'
const RUNTIME_FIXTURE_MATCH = '**/jest.quarantine.runtime.fixture.ts'

function entry(overrides: Partial<QuarantineEntry> = {}): QuarantineEntry {
    return {
        id: 'frontend/src/x.test.ts',
        mode: 'run',
        reason: 'flaky',
        owner: '@web',
        issue: '',
        expires: '2026-06-20',
        ...overrides,
    }
}

function runtimeEntry(id: string, mode: 'run' | 'skip' = 'run'): Record<string, string> {
    return {
        id,
        runner: 'jest',
        reason: 'runtime quarantine adapter test',
        owner: '@team-devex',
        added: TODAY,
        expires: '2099-12-31',
        mode,
    }
}

describe('jest.quarantine', () => {
    describe('selectorMatches', () => {
        // The JS reimplements core.py's grammar, so it can drift independently; these lock it.
        test.each<[string, string, string, boolean]>([
            ['file covers a test in it', 'frontend/src/x.test.ts', 'frontend/src/x.test.ts::A loads', true],
            ['directory prefix', 'frontend/src', 'frontend/src/x.test.ts::A loads', true],
            ['directory trailing slash', 'frontend/src/', 'frontend/src/x.test.ts::A loads', true],
            ['describe prefix via space', 'frontend/src/x.test.ts::A', 'frontend/src/x.test.ts::A loads data', true],
            ['exact full name', 'frontend/src/x.test.ts::A loads', 'frontend/src/x.test.ts::A loads', true],
            ['partial describe word', 'frontend/src/x.test.ts::A lo', 'frontend/src/x.test.ts::A loads', false],
            ['product selector', 'product:batch-exports', 'products/batch_exports/frontend/x.test.ts::A', true],
            ['product mismatch', 'product:batch-exports', 'frontend/src/x.test.ts::A', false],
            ['unrelated sibling file', 'frontend/src/x.test.ts', 'frontend/src/xy.test.ts::A', false],
        ])('%s', (_label, selector, testId, expected) => {
            expect(selectorMatches(selector, testId)).toBe(expected)
        })
    })

    describe('activeJestEntries', () => {
        test('keeps only unexpired jest entries', () => {
            const raw = [
                { id: 'a', runner: 'jest', expires: '2026-06-20' },
                { id: 'b', runner: 'jest', expires: '2026-06-01' }, // expired
                { id: 'c', expires: '2026-06-20' }, // defaults to pytest
                { id: 'd', runner: 'pytest', expires: '2026-06-20' },
                { id: 'e', runner: 'jest', mode: 'pause', expires: '2026-06-20' }, // invalid mode dropped
                { id: 'f', runner: 'jest', mode: 'skip', expires: '2026-06-20' },
                { id: 'g', runner: 'jest', expires: 'not-a-date' }, // malformed expiry would sort after today and mask forever
                { id: 'h', runner: 'jest', expires: '2026-9-05' }, // non-canonical ISO, same trap
            ]
            expect(activeJestEntries(raw, TODAY).map((e) => e.id)).toEqual(['a', 'f'])
        })
    })

    describe('findMatch', () => {
        test('the most specific selector wins so a narrow skip overrides a broad run', () => {
            const entries = [
                entry({ id: 'frontend/src/x.test.ts', mode: 'run' }),
                entry({ id: 'frontend/src/x.test.ts::A loads', mode: 'skip' }),
            ]
            expect(findMatch(entries, 'frontend/src/x.test.ts::A loads')?.mode).toBe('skip')
            expect(findMatch(entries, 'frontend/src/x.test.ts::B other')?.mode).toBe('run')
        })

        test('returns null when nothing matches', () => {
            expect(findMatch([entry()], 'frontend/src/other.test.ts::A')).toBeNull()
        })
    })

    describe('parseQuarantine', () => {
        test('reads v1 entries and drops ones without an id', () => {
            const text = JSON.stringify({
                version: 1,
                entries: [{ id: 'frontend/src/x.test.ts', runner: 'jest' }, { runner: 'jest' }],
            })
            expect(parseQuarantine(text).map((e) => e.id)).toEqual(['frontend/src/x.test.ts'])
        })

        test.each<[string, string]>([
            ['unsupported version', JSON.stringify({ version: 2, entries: [{ id: 'a' }] })],
            ['entries not a list', JSON.stringify({ version: 1, entries: {} })],
        ])('returns [] for %s', (_label, text) => {
            expect(parseQuarantine(text)).toEqual([])
        })
    })

    describe('repoRelativePath', () => {
        test('makes an absolute test path repo-root-relative with forward slashes', () => {
            expect(repoRelativePath('/repo/frontend/src/x.test.ts', '/repo')).toBe('frontend/src/x.test.ts')
        })
    })

    describe('productPathPrefix', () => {
        test('maps a dashed product name to the underscored directory', () => {
            expect(productPathPrefix('product:batch-exports')).toBe('products/batch_exports/')
        })
    })

    describe('runtime adapter', () => {
        test('enforces skip and tolerated failures in a real jest worker', () => {
            expect.hasAssertions()
            const fixtureSuiteId = `${RUNTIME_FIXTURE_ID}::jest quarantine runtime fixture`
            const payload = {
                version: 1,
                entries: [
                    runtimeEntry(fixtureSuiteId),
                    runtimeEntry(`${fixtureSuiteId} tolerates body failure`),
                    runtimeEntry(`${fixtureSuiteId} tolerates async rejection`),
                    runtimeEntry(`${fixtureSuiteId} tolerates beforeEach failure`),
                    runtimeEntry(`${fixtureSuiteId} tolerates afterEach failure`),
                    runtimeEntry(`${fixtureSuiteId} skips body`, 'skip'),
                ],
            }

            // Write to an isolated temp file, never the committed repo-root one, so parallel
            // workers and a killed run can't read or leave behind fixture-only entries.
            const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'jest-quarantine-'))
            const quarantinePath = path.join(tmpDir, '.test_quarantine.json')
            try {
                fs.writeFileSync(quarantinePath, `${JSON.stringify(payload, null, 4)}\n`)
                const result = spawnSync(
                    path.join(FRONTEND_DIR, 'node_modules/.bin/jest'),
                    [
                        '--config',
                        path.join(FRONTEND_DIR, 'jest.config.ts'),
                        '--runInBand',
                        '--no-cache',
                        '--testMatch',
                        RUNTIME_FIXTURE_MATCH,
                    ],
                    {
                        cwd: FRONTEND_DIR,
                        encoding: 'utf-8',
                        env: { ...process.env, CI: '1', POSTHOG_TEST_QUARANTINE_PATH: quarantinePath },
                    }
                )
                const output = `${result.stdout}\n${result.stderr}`
                if (result.status !== 0) {
                    throw new Error(`fixture jest run failed with status ${result.status}\n${output}`)
                }
                expect(output).toContain('[quarantine] tolerated failure')
                expect(output).toContain('quarantined body failure')
                expect(output).toContain('quarantined beforeEach failure')
                expect(output).toContain('quarantined afterEach failure')
                expect(output).toContain('[quarantine] skipping')
                expect(output).not.toContain('skipped body should not run')
            } finally {
                fs.rmSync(tmpDir, { recursive: true, force: true })
            }
        }, 30000)
    })
})
