/**
 * Playwright adapter for the test quarantine — pure contract logic + loader.
 *
 * Schema contract: tools/hogli-commands/hogli_commands/quarantine/core.py — this
 * file consumes that contract for `runner: "playwright"` entries and must not
 * reimplement parsing, date handling, or matching beyond what it documents.
 * It is the Playwright sibling of `quarantine/pytest_support.py`.
 *
 * A playwright id is `<repo-relative-spec>::<full test name>`, where the name is
 * the space-joined ancestor `describe` titles plus the `test`/`it` title.
 *
 * The two halves of enforcement live next to this pure core:
 *   - `mode: "skip"` — an auto fixture in `utils/playwright-test-core.ts` calls
 *     `test.skip()` before the body runs (for hangs / state-polluters).
 *   - `mode: "run"` — Playwright has no native non-strict xfail, so the test
 *     still executes and `playwright.quarantine.reporter.ts` tolerates a
 *     failure by overriding the run status, keeping timing/outcome flowing.
 *
 * Fail-open: any problem reading or applying the file yields no active entries
 * and the run proceeds normally. This module imports only Node stdlib so the
 * pure logic can be unit-tested without pulling in `@playwright/test`.
 */

import * as fs from 'fs'
import * as path from 'path'

const SCHEMA_VERSION = 1
const DEFAULT_RUNNER = 'pytest'
const RUNNER = 'playwright'
const PRODUCT_PREFIX = 'product:'

// __dirname is <repo>/playwright, so the repo root is one directory up.
export const REPO_ROOT = path.resolve(__dirname, '..')
const QUARANTINE_PATH = path.join(REPO_ROOT, '.test_quarantine.json')

interface RawEntry {
    id: string
    runner?: string
    mode?: string
    reason?: string
    owner?: string
    issue?: string
    added?: string
    expires?: string
}

export interface QuarantineEntry {
    id: string
    mode: 'run' | 'skip'
    reason: string
    owner: string
    issue: string
    expires: string
}

export interface QuarantineDecision {
    mode: 'run' | 'skip'
    /** Human-readable line for skip warnings / tolerated-failure logs. */
    label: string
}

// --- Pure contract logic (mirrors core.py; unit-tested in playwright.quarantine.test.ts) ---

export function productPathPrefix(selector: string): string {
    const name = selector.slice(PRODUCT_PREFIX.length)
    return `products/${name.replace(/-/g, '_')}/`
}

/** Does `selector` cover `testId`? See the playwright grammar in core.py's docstring. */
export function selectorMatches(selector: string, testId: string): boolean {
    if (selector.startsWith(PRODUCT_PREFIX)) {
        return testId.startsWith(productPathPrefix(selector))
    }
    const trimmed = selector.replace(/\/+$/, '')
    return (
        testId === trimmed ||
        testId.startsWith(`${trimmed}/`) ||
        testId.startsWith(`${trimmed}::`) ||
        testId.startsWith(`${trimmed}[`) ||
        testId.startsWith(`${trimmed} `)
    )
}

function expandedSelector(selector: string): string {
    return selector.startsWith(PRODUCT_PREFIX) ? productPathPrefix(selector) : selector
}

/** The most specific (longest) matching selector wins, so a narrow skip overrides a broad run. */
export function findMatch(entries: QuarantineEntry[], testId: string): QuarantineEntry | null {
    let best: QuarantineEntry | null = null
    let bestLength = -1
    for (const entry of entries) {
        if (!selectorMatches(entry.id, testId)) {
            continue
        }
        const length = expandedSelector(entry.id).length
        if (length > bestLength) {
            best = entry
            bestLength = length
        }
    }
    return best
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null
}

function isRawEntry(value: unknown): value is RawEntry {
    return isRecord(value) && typeof value.id === 'string' && value.id.length > 0
}

/** Parse v1 quarantine JSON into raw entries. Throws only on invalid JSON (caller fails open). */
export function parseQuarantine(text: string): RawEntry[] {
    const data: unknown = JSON.parse(text)
    if (!isRecord(data) || data.version !== SCHEMA_VERSION || !Array.isArray(data.entries)) {
        return []
    }
    return data.entries.filter(isRawEntry)
}

/**
 * True only for a real `YYYY-MM-DD` calendar date. `expires` is compared
 * lexicographically below, so a non-zero-padded ('2026-9-05') or non-date
 * ('soon') string would sort wrong and mask a test forever — core.py's
 * `date.fromisoformat` rejects those, and this guard keeps the reader in step
 * (fail-safe: an unparseable expiry drops the entry rather than activating it).
 */
export function isIsoDate(value: string): boolean {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
        return false
    }
    const parsed = new Date(`${value}T00:00:00Z`)
    return !isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
}

/** Unexpired `runner: "playwright"` entries only — other runners and expired entries are excluded. */
export function activePlaywrightEntries(entries: RawEntry[], todayIso: string): QuarantineEntry[] {
    const active: QuarantineEntry[] = []
    for (const entry of entries) {
        if ((entry.runner ?? DEFAULT_RUNNER) !== RUNNER) {
            continue
        }
        if (typeof entry.expires !== 'string' || !isIsoDate(entry.expires) || entry.expires < todayIso) {
            continue
        }
        if (entry.mode !== undefined && entry.mode !== 'run' && entry.mode !== 'skip') {
            continue
        }
        active.push({
            id: entry.id,
            mode: entry.mode === 'skip' ? 'skip' : 'run',
            reason: entry.reason ?? '',
            owner: entry.owner ?? '',
            issue: entry.issue ?? '',
            expires: entry.expires,
        })
    }
    return active
}

/** Repo-root-relative, forward-slash path for an absolute spec file path. */
export function repoRelativePath(absolutePath: string, repoRoot: string = REPO_ROOT): string {
    return path.relative(repoRoot, absolutePath).split(path.sep).join('/')
}

/** `<repo-relative-spec>::<describe… test>` — the canonical playwright id. */
export function testId(fileRelPath: string, nameParts: string[]): string {
    return `${fileRelPath}::${nameParts.join(' ')}`
}

function toDecision(entry: QuarantineEntry, id: string): QuarantineDecision {
    const attribution = entry.issue || entry.owner || 'no owner'
    return {
        mode: entry.mode,
        label: `${id} — quarantined until ${entry.expires}: ${entry.reason} (${attribution})`,
    }
}

/** The active entry (as a decision) covering a test, or null. Shared by the fixture and reporter. */
export function decideForTest(
    entries: QuarantineEntry[],
    absoluteFile: string,
    nameParts: string[],
    repoRoot: string = REPO_ROOT
): QuarantineDecision | null {
    const id = testId(repoRelativePath(absoluteFile, repoRoot), nameParts)
    const entry = findMatch(entries, id)
    return entry ? toDecision(entry, id) : null
}

// --- Loader (runtime side; fail-open) ---

function todayIso(): string {
    return new Date().toISOString().slice(0, 10)
}

/** Read the active playwright entries, or [] on any problem (missing/malformed file). */
export function loadActiveEntries(quarantinePath: string = QUARANTINE_PATH): QuarantineEntry[] {
    let text: string
    try {
        text = fs.readFileSync(quarantinePath, 'utf-8')
    } catch {
        return [] // A missing file means quarantine is simply off.
    }
    try {
        return activePlaywrightEntries(parseQuarantine(text), todayIso())
    } catch {
        return [] // Malformed file: fail open rather than break the run.
    }
}
