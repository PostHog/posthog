import { spawnSync } from 'child_process'
import { mkdtempSync, rmSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import { join, resolve } from 'path'

const REPO_ROOT = resolve(__dirname, '..', '..')
const CHECKER = join(REPO_ROOT, 'frontend', 'bin', 'check-eager-graph.mjs')
const SHELL = 'src/scenes/AuthenticatedShell.tsx'
const SHELL_BASE_BYTES = 7_000_000

interface EagerGraphRoot {
    bytes?: number
    forbiddenHits: { chain: string[]; module: string }[]
    label?: string
    largest: { bytes: number; file: string }[]
    overBudget: boolean
    root: string
}

interface EagerGraphReport {
    errors: string[]
    roots: EagerGraphRoot[]
    sha?: string
    warnings: string[]
}

function runChecker(
    report: EagerGraphReport,
    { baseReport, labels }: { baseReport?: EagerGraphReport; labels?: string[] } = {}
): number | null {
    const directory = mkdtempSync(join(tmpdir(), 'eager-graph-'))
    const reportPath = join(directory, 'report.json')
    const baseReportPath = join(directory, 'base-report.json')
    const labelsPath = join(directory, 'labels.txt')
    writeFileSync(reportPath, JSON.stringify(report))
    if (baseReport) {
        writeFileSync(baseReportPath, JSON.stringify(baseReport))
    }
    if (labels) {
        writeFileSync(labelsPath, labels.join('\n'))
    }

    try {
        return spawnSync(
            'node',
            [CHECKER, '--assert-report', reportPath, '--fail-forbidden-hits', '--base-report', baseReportPath],
            {
                cwd: REPO_ROOT,
                encoding: 'utf8',
                env: { ...process.env, PR_LABELS_FILE: labelsPath },
            }
        ).status
    } finally {
        rmSync(directory, { recursive: true, force: true })
    }
}

function shellReport(sha: string, bytes: number): EagerGraphReport {
    return {
        errors: [],
        roots: [
            { root: SHELL, label: 'authenticated shell', bytes, forbiddenHits: [], largest: [], overBudget: false },
        ],
        sha,
        warnings: [],
    }
}

describe('check-eager-graph.mjs', () => {
    it.each([
        [
            'a forbidden eager import',
            [{ module: 'node_modules/monaco-editor/', chain: ['src/index.tsx'] }],
            [],
            false,
            1,
        ],
        ['an analysis error', [], ['No output chunk found for src/index.tsx'], false, 1],
        ['a budget warning', [], [], true, 0],
    ])('fails only for %s', (_, forbiddenHits, errors, overBudget, expectedStatus) => {
        expect(
            runChecker({
                errors,
                roots: [{ root: 'src/index.tsx', forbiddenHits, largest: [], overBudget }],
                warnings: [],
            })
        ).toBe(expectedStatus)
    })

    it.each([
        ['growth under the limit', 19 * 1024, true, [], 0],
        ['growth over the limit', 21 * 1024, true, [], 1],
        ['growth over the limit with the approval label', 21 * 1024, true, ['eager-growth-approved'], 0],
        ['growth over the limit with no base report', 21 * 1024, false, [], 0],
    ])('gates the shell on %s', (_, growthBytes, hasBaseReport, labels, expectedStatus) => {
        expect(
            runChecker(shellReport('pr-sha', SHELL_BASE_BYTES + growthBytes), {
                baseReport: hasBaseReport ? shellReport('base-sha', SHELL_BASE_BYTES) : undefined,
                labels,
            })
        ).toBe(expectedStatus)
    })
})
