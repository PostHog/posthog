/**
 * Jest adapter for the test quarantine.
 *
 * Schema contract: tools/hogli-commands/hogli_commands/quarantine/core.py; this
 * file consumes that contract for `runner: "jest"` entries and must not
 * reimplement parsing, date handling, or matching beyond what it documents.
 * It is the jest sibling of `quarantine/pytest_support.py`.
 *
 * A jest id is `<repo-relative-file>::<full test name>`, where the name is the
 * space-joined ancestor `describe` titles plus the `it`/`test` title (jest's
 * `currentTestName`). Installed as a `setupFilesAfterEnv` module, it wraps the
 * `describe`/`it`/`test` globals and lifecycle hooks so a matching active entry
 * either skips the test (`mode: "skip"`, for hangs/state-polluters) or
 * tolerates its body and matching hook failures (`mode: "run"`, since jest has
 * no native non-strict xfail, so failures are swallowed instead of failing the
 * suite).
 *
 * Fail-open: any problem reading or applying the file leaves the globals
 * untouched and the run proceeds normally.
 *
 * Granularity note: `describe.each` block titles and `it.each` row titles are
 * resolved by jest after collection. Exact row selectors support `mode: "run"`
 * through the runtime test name; `mode: "skip"` still requires file, directory,
 * or `product:` scope because jest decides skips during collection.
 */

import * as fs from 'fs'
import * as path from 'path'

const SCHEMA_VERSION = 1
// Mirrors PYTEST_RUNNER/JEST_RUNNER in core.py; pytest is also the schema default when an entry omits `runner`.
const PYTEST_RUNNER = 'pytest'
const JEST_RUNNER = 'jest'
const PRODUCT_PREFIX = 'product:'

// __dirname is <repo>/frontend, so the repo root is one directory up.
const REPO_ROOT = path.resolve(__dirname, '..')
// Overridable so the adapter's own runtime test can point a spawned jest worker
// at an isolated fixture file instead of the committed repo-root one.
const QUARANTINE_PATH = process.env.POSTHOG_TEST_QUARANTINE_PATH || path.join(REPO_ROOT, '.test_quarantine.json')

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

// --- Pure contract logic (mirrors core.py; unit-tested in jest.quarantine.test.ts) ---

export function productPathPrefix(selector: string): string {
    const name = selector.slice(PRODUCT_PREFIX.length)
    return `products/${name.replace(/-/g, '_')}/`
}

/** Does `selector` cover `testId`? See the jest grammar in core.py's module docstring. */
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
 * Expiry compares lexicographically, so a malformed date (e.g. `2026-9-05` or free
 * text) would sort after today and quarantine a test forever. The contract's
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

/** Unexpired `runner: "jest"` entries only; other runners and expired entries are excluded. */
export function activeJestEntries(entries: RawEntry[], todayIso: string): QuarantineEntry[] {
    const active: QuarantineEntry[] = []
    for (const entry of entries) {
        if ((entry.runner ?? PYTEST_RUNNER) !== JEST_RUNNER) {
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

/** Repo-root-relative, forward-slash path for a jest `testPath` (absolute). */
export function repoRelativePath(absolutePath: string, repoRoot: string = REPO_ROOT): string {
    return path.relative(repoRoot, absolutePath).split(path.sep).join('/')
}

// --- Runtime wiring: read the file, then wrap the jest globals ---

let activeEntries: QuarantineEntry[] = []
const describeStack: string[] = []

interface Decision {
    mode: 'run' | 'skip'
    label: string
    testId: string
}

function todayIso(): string {
    return new Date().toISOString().slice(0, 10)
}

function loadActiveEntries(): QuarantineEntry[] {
    let text: string
    try {
        text = fs.readFileSync(QUARANTINE_PATH, 'utf-8')
    } catch {
        return [] // A missing file means quarantine is simply off.
    }
    let raw: RawEntry[]
    try {
        raw = parseQuarantine(text)
    } catch {
        return [] // Malformed file: fail open rather than break collection.
    }
    return activeJestEntries(raw, todayIso())
}

function stringifyName(name: unknown): string {
    if (typeof name === 'function') {
        return (name as { name?: string }).name ?? ''
    }
    return String(name)
}

// `expect` may not be initialized yet while setup files run, so read defensively.
function jestState(): ReturnType<typeof expect.getState> | undefined {
    try {
        return expect.getState()
    } catch {
        return undefined
    }
}

function currentTestPath(): string | undefined {
    return jestState()?.testPath ?? undefined
}

function currentTestName(): string | undefined {
    const name = jestState()?.currentTestName
    return typeof name === 'string' && name.length > 0 ? name : undefined
}

function toDecision(entry: QuarantineEntry, testId: string): Decision {
    const attribution = entry.issue || entry.owner || 'no owner'
    return {
        mode: entry.mode,
        label: `${testId}: quarantined until ${entry.expires}: ${entry.reason} (${attribution})`,
        testId,
    }
}

// testPath is constant for a whole file run, so cache its repo-relative form
// rather than recomputing path.relative on every test declaration.
let cachedTestPath: string | undefined
let cachedRelativePath = ''

function relativeTestPath(): string | null {
    const testPath = currentTestPath()
    if (testPath === undefined) {
        return null
    }
    if (testPath !== cachedTestPath) {
        cachedTestPath = testPath
        cachedRelativePath = repoRelativePath(testPath)
    }
    return cachedRelativePath
}

function decideFor(testId: string): Decision | null {
    const entry = findMatch(activeEntries, testId)
    return entry ? toDecision(entry, testId) : null
}

function decideForTest(name: unknown): Decision | null {
    const relativePath = relativeTestPath()
    if (relativePath === null) {
        return null
    }
    return decideFor(`${relativePath}::${[...describeStack, stringifyName(name)].join(' ')}`)
}

function decideForRunningTest(): Decision | null {
    const relativePath = relativeTestPath()
    const name = currentTestName()
    if (relativePath === null || name === undefined) {
        return null
    }
    return decideFor(`${relativePath}::${name}`)
}

function decideForFile(): Decision | null {
    const relativePath = relativeTestPath()
    return relativePath === null ? null : decideFor(relativePath)
}

function decideForScope(): Decision | null {
    const relativePath = relativeTestPath()
    if (relativePath === null) {
        return null
    }
    const scopeId = describeStack.length > 0 ? `${relativePath}::${describeStack.join(' ')}` : relativePath
    return decideFor(scopeId)
}

function errorText(error: unknown): string {
    if (error instanceof Error) {
        return error.stack ?? error.message
    }
    return String(error)
}

function warn(message: string): void {
    // eslint-disable-next-line no-console
    console.warn(message)
}

function warnSkip(decision: Decision): void {
    warn(`[quarantine] skipping ${decision.label}`)
}

function warnTolerated(decision: Decision, error: unknown): void {
    recordToleratedFailure(decision.testId)
    warn(`[quarantine] tolerated failure in ${decision.label}\n${errorText(error)}`)
}

const recordedToleratedFailures = new Set<string>()

function recordToleratedFailure(testId: string): void {
    const outputDirectory = process.env.JEST_JUNIT_OUTPUT_DIR
    if (!outputDirectory || recordedToleratedFailures.has(testId)) {
        return
    }
    try {
        fs.mkdirSync(outputDirectory, { recursive: true })
        fs.appendFileSync(
            path.join(outputDirectory, `posthog-jest-quarantine-${process.pid}.jsonl`),
            `${JSON.stringify({ test_id: testId })}\n`
        )
        recordedToleratedFailures.add(testId)
    } catch {
        // Telemetry is best-effort; quarantine enforcement must still work without it.
    }
}

function isThenable(value: unknown): value is PromiseLike<unknown> {
    return isRecord(value) && typeof (value as { then?: unknown }).then === 'function'
}

/** Run a callback swallowing any thrown error or rejected promise (jest's non-strict xfail analog). */
function tolerate(fn: (...args: unknown[]) => unknown, decision: Decision): (...args: unknown[]) => unknown {
    return function (this: unknown, ...args: unknown[]): unknown {
        try {
            const result = fn.apply(this, args)
            if (isThenable(result)) {
                return result.then(undefined, (error: unknown) => {
                    warnTolerated(decision, error)
                    return undefined
                })
            }
            return result
        } catch (error) {
            warnTolerated(decision, error)
            return undefined
        }
    }
}

function runDoneStyle(
    fn: jest.ProvidesCallback | ((...args: unknown[]) => unknown),
    args: unknown[],
    decision: Decision,
    done: jest.DoneCallback,
    thisArg: unknown
): void {
    let finished = false
    const finish = (): void => {
        if (!finished) {
            finished = true
            done()
        }
    }
    const tolerantDone = function (reason?: string | Error): void {
        if (reason !== undefined) {
            warnTolerated(decision, reason)
        }
        finish()
    } as jest.DoneCallback
    tolerantDone.fail = function (reason?: string | Error): void {
        warnTolerated(decision, reason ?? new Error('done.fail() called'))
        finish()
    }
    try {
        const doneStyle = fn as (...callbackArgs: unknown[]) => unknown
        doneStyle.call(thisArg, ...args, tolerantDone)
    } catch (error) {
        warnTolerated(decision, error)
        finish()
    }
}

/**
 * Tolerate an `it`/`test` body or hook, handling the done-callback style that
 * `tolerate` can't (it swallows via the promise/throw path).
 */
function tolerateProvidesWhen(
    fn: jest.ProvidesCallback | undefined,
    getDecision: () => Decision | null
): jest.ProvidesCallback | undefined {
    if (typeof fn !== 'function') {
        return fn
    }
    if (fn.length >= 1) {
        const doneStyle = fn as (done: jest.DoneCallback) => void
        return function (this: unknown, done: jest.DoneCallback): void {
            const decision = getDecision()
            if (decision === null || decision.mode !== 'run') {
                doneStyle.call(this, done)
                return
            }
            runDoneStyle(doneStyle, [], decision, done, this)
        }
    }
    return function (this: unknown): unknown {
        const decision = getDecision()
        if (decision === null || decision.mode !== 'run') {
            return (fn as () => unknown).call(this)
        }
        return tolerate(fn as () => unknown, decision).call(this)
    } as jest.ProvidesCallback
}

/** Copy every own member (skip/only/todo/each/…) from a jest global onto its wrapper. */
function copyMembers(target: object, source: object): void {
    for (const key of Object.getOwnPropertyNames(source)) {
        if (key === 'length' || key === 'name' || key === 'prototype') {
            continue
        }
        const descriptor = Object.getOwnPropertyDescriptor(source, key)
        if (descriptor) {
            Object.defineProperty(target, key, descriptor)
        }
    }
}

type EachFactory = (name: string, fn: (...args: unknown[]) => unknown, timeout?: number) => void
type EachEntry = (...args: unknown[]) => EachFactory

function eachArgumentCount(eachArgs: unknown[]): number | null {
    const [table, ...templateValues] = eachArgs
    if (templateValues.length > 0) {
        return 1
    }
    if (!Array.isArray(table) || table.length === 0) {
        return null
    }
    const counts = table.map((row) => (Array.isArray(row) ? row.length : 1))
    return counts.every((count) => count === counts[0]) ? counts[0] : null
}

function tolerateEachWhen(
    fn: (...args: unknown[]) => unknown,
    getDecision: () => Decision | null,
    argumentCount: number | null
): (...args: unknown[]) => unknown {
    const wrapped = function (this: unknown, ...args: unknown[]): unknown {
        const decision = getDecision()
        if (decision === null || decision.mode !== 'run') {
            return fn.apply(this, args)
        }
        if (argumentCount !== null && fn.length > argumentCount && args.length === argumentCount + 1) {
            const done = args[argumentCount]
            if (typeof done === 'function') {
                runDoneStyle(fn, args.slice(0, argumentCount), decision, done as jest.DoneCallback, this)
                return undefined
            }
        }
        return tolerate(fn, decision).apply(this, args)
    }
    // jest-each compares callback arity with row width to decide whether to inject `done`.
    Object.defineProperty(wrapped, 'length', { value: fn.length })
    return wrapped
}

/** `.each`: collection-time file scopes can skip; runtime row identities can tolerate failures. */
function wrapEach(base: jest.It, skipBase: jest.It): jest.Each {
    const wrapped = (...eachArgs: unknown[]): EachFactory => {
        const factory = (base.each as unknown as EachEntry)(...eachArgs)
        const decision = decideForFile()
        if (decision?.mode === 'skip') {
            warnSkip(decision)
            return (skipBase.each as unknown as EachEntry)(...eachArgs)
        }
        const argumentCount = eachArgumentCount(eachArgs)
        return (name: string, fn: (...args: unknown[]) => unknown, timeout?: number): void =>
            factory(name, tolerateEachWhen(fn, decideForRunningTest, argumentCount), timeout)
    }
    return wrapped as unknown as jest.Each
}

function wrapIt(original: jest.It, wrapConcurrent = true): jest.It {
    const run = (source: jest.It, name: string, fn?: jest.ProvidesCallback, timeout?: number): void => {
        const decision = decideForTest(name)
        if (decision?.mode === 'skip') {
            warnSkip(decision)
            original.skip(name, fn, timeout)
            return
        }
        source(name, tolerateProvidesWhen(fn, decideForRunningTest), timeout)
    }

    const wrapped = ((name: string, fn?: jest.ProvidesCallback, timeout?: number): void => {
        run(original, name, fn, timeout)
    }) as jest.It
    copyMembers(wrapped, original)

    const wrappedOnly = ((name: string, fn?: jest.ProvidesCallback, timeout?: number): void => {
        run(original.only, name, fn, timeout)
    }) as jest.It
    copyMembers(wrappedOnly, original.only)
    wrappedOnly.each = wrapEach(original.only, original.skip)
    wrapped.only = wrappedOnly

    if (wrapConcurrent && typeof original.concurrent === 'function') {
        wrapped.concurrent = wrapIt(original.concurrent, false)
    }
    wrapped.each = wrapEach(original, original.skip)
    return wrapped
}

type DescribeName = Parameters<jest.Describe>[0]
type DescribeBody = Parameters<jest.Describe>[1]

function wrapDescribeVariant(variant: jest.Describe): jest.Describe {
    const wrapped = ((name: DescribeName, fn: DescribeBody): void => {
        variant(name, function (this: unknown): void {
            describeStack.push(stringifyName(name))
            try {
                fn.call(this)
            } finally {
                describeStack.pop()
            }
        })
    }) as jest.Describe
    copyMembers(wrapped, variant)
    return wrapped
}

function wrapDescribe(original: jest.Describe): jest.Describe {
    const wrapped = wrapDescribeVariant(original)
    // `.only`/`.skip` also nest, so keep the stack correct through them.
    wrapped.only = wrapDescribeVariant(original.only)
    wrapped.skip = wrapDescribeVariant(original.skip)
    return wrapped
}

function wrapLifecycle(
    original: jest.Lifecycle,
    getDecision: () => Decision | null,
    useDeclarationDecision = false
): jest.Lifecycle {
    return ((fn: jest.ProvidesHookCallback, timeout?: number): void => {
        const declarationDecision = useDeclarationDecision ? getDecision() : null
        original(
            tolerateProvidesWhen(
                fn as jest.ProvidesCallback,
                () => declarationDecision ?? getDecision()
            ) as jest.ProvidesHookCallback,
            timeout
        )
    }) as jest.Lifecycle
}

function install(entries: QuarantineEntry[]): void {
    if (entries.length === 0) {
        return
    }
    const globals = globalThis as typeof globalThis & {
        describe: jest.Describe
        it: jest.It
        test: jest.It
        beforeEach: jest.Lifecycle
        afterEach: jest.Lifecycle
        beforeAll: jest.Lifecycle
        afterAll: jest.Lifecycle
    }
    if (typeof globals.describe === 'function') {
        globals.describe = wrapDescribe(globals.describe)
    }
    if (typeof globals.it === 'function') {
        globals.it = wrapIt(globals.it)
    }
    if (typeof globals.test === 'function') {
        globals.test = wrapIt(globals.test)
    }
    if (typeof globals.beforeEach === 'function') {
        globals.beforeEach = wrapLifecycle(globals.beforeEach, decideForRunningTest)
    }
    if (typeof globals.afterEach === 'function') {
        globals.afterEach = wrapLifecycle(globals.afterEach, decideForRunningTest)
    }
    if (typeof globals.beforeAll === 'function') {
        globals.beforeAll = wrapLifecycle(globals.beforeAll, decideForScope, true)
    }
    if (typeof globals.afterAll === 'function') {
        globals.afterAll = wrapLifecycle(globals.afterAll, decideForScope, true)
    }
}

try {
    activeEntries = loadActiveEntries()
    install(activeEntries)
} catch (error) {
    warn(`[quarantine] disabled: ${errorText(error)}`)
}
