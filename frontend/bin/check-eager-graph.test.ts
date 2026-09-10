import { spawnSync } from 'child_process'
import { mkdtempSync, rmSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import { join, resolve } from 'path'

const REPO_ROOT = resolve(__dirname, '..', '..')
const CHECKER = join(REPO_ROOT, 'frontend', 'bin', 'check-eager-graph.mjs')

interface EagerGraphReport {
    errors: string[]
    roots: {
        forbiddenHits: { chain: string[]; module: string }[]
        largest: { bytes: number; file: string }[]
        overBudget: boolean
        root: string
    }[]
    warnings: string[]
}

function runChecker(report: EagerGraphReport): number | null {
    const directory = mkdtempSync(join(tmpdir(), 'eager-graph-'))
    const reportPath = join(directory, 'report.json')
    writeFileSync(reportPath, JSON.stringify(report))

    try {
        return spawnSync('node', [CHECKER, '--assert-report', reportPath, '--fail-forbidden-hits'], {
            cwd: REPO_ROOT,
            encoding: 'utf8',
        }).status
    } finally {
        rmSync(directory, { recursive: true, force: true })
    }
}

describe('check-eager-graph.mjs', () => {
    it.each([
        ['a forbidden eager import', [{ module: 'node_modules/monaco-editor/', chain: ['src/index.tsx'] }], [], false, 1],
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
})
