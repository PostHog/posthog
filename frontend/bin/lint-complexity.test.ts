import { execFileSync } from 'child_process'
import { mkdtempSync, rmSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import { join, resolve } from 'path'

const REPO_ROOT = resolve(__dirname, '..', '..')
const LINTER = join(REPO_ROOT, 'bin', 'lint-complexity.mjs')

// Cyclomatic complexity = branches + 1.
function branchyFunction(branches: number): string {
    const checks = Array.from({ length: branches }, (_, i) => `    if (n === ${i}) return ${i}\n`).join('')
    return `export function probe(n: number): number {\n${checks}    return -1\n}\n`
}

interface Finding {
    file: string
    limit: number
}

describe('lint-complexity.mjs', () => {
    let fixtureDir: string

    beforeEach((): void => {
        fixtureDir = mkdtempSync(join(tmpdir(), 'lint-complexity-'))
    })

    afterEach((): void => {
        rmSync(fixtureDir, { recursive: true, force: true })
    })

    function runLinter(target: string, flags: string[] = []): string {
        return execFileSync('node', [LINTER, ...flags, target], { cwd: REPO_ROOT, encoding: 'utf8' })
    }

    function lintJson(filename: string, branches: number): Finding[] {
        const target = join(fixtureDir, filename)
        writeFileSync(target, branchyFunction(branches))
        return JSON.parse(runLinter(target, ['--json'])) as Finding[]
    }

    it('warns a production file at complexity 12 with limit 10', (): void => {
        const findings = lintJson('probe.ts', 11)
        expect(findings.map((finding) => finding.limit)).toEqual([10])
    })

    it('does not warn a test file at complexity 12', (): void => {
        expect(lintJson('probe.test.ts', 11)).toEqual([])
    })

    it('warns a test file at complexity 17 with limit 15', (): void => {
        const findings = lintJson('probe.test.ts', 16)
        expect(findings.map((finding) => finding.limit)).toEqual([15])
    })

    it('reports the first file argument on a bare invocation', (): void => {
        // ci-frontend.yml passes --report and hogli passes --json, both leading
        // flags. A bare invocation must not drop the first file argument.
        const target = join(fixtureDir, 'probe.tsx')
        writeFileSync(target, branchyFunction(11))

        const output = runLinter(target)

        expect(output).toContain('warning')
        expect(output).toContain('warn >10')
    })
})
