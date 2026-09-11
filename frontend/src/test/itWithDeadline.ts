import { spawnSync } from 'node:child_process'
import path from 'node:path'

const CHILD_MARKER = 'POSTHOG_DEADLINE_TEST_CHILD'
const DEADLINE_MS = 30000
const FRONTEND_DIR = path.resolve(__dirname, '../..')

export function runNodeWithDeadline(args: string[], timeoutMs = DEADLINE_MS, env = process.env): string {
    const result = spawnSync(process.execPath, args, {
        cwd: FRONTEND_DIR,
        env,
        encoding: 'utf8',
        timeout: timeoutMs,
        killSignal: 'SIGKILL',
        maxBuffer: 1024 * 1024,
    })
    if (result.error || result.signal || result.status !== 0) {
        throw new Error(
            `Child failed: status ${result.status}, signal ${result.signal}, error ${result.error}\n${(
                (result.stderr || '') + (result.stdout || '')
            ).slice(0, 8192)}`
        )
    }
    if (result.stderr) {
        process.stderr.write(result.stderr)
    }
    return result.stdout
}

// A Jest timer cannot interrupt synchronous matching; only the disposable child runs the body.
export function itWithDeadline(name: string, body: () => void): void {
    it(
        name,
        () => {
            const { testPath, currentTestName } = expect.getState()
            if (!testPath || !currentTestName) {
                throw new Error('A deadline test must run inside a named Jest test')
            }
            if (process.env[CHILD_MARKER]) {
                const expectedMarker = JSON.stringify([process.ppid, testPath, currentTestName])
                if (process.env[CHILD_MARKER] !== expectedMarker) {
                    throw new Error('Unexpected deadline child test; refusing to run or spawn recursively')
                }
                expect.hasAssertions()
                body()
                return
            }

            const output = runNodeWithDeadline(
                [
                    require.resolve('jest/bin/jest'),
                    '--config',
                    path.join(FRONTEND_DIR, 'jest.config.ts'),
                    '--runInBand',
                    '--watchman=false',
                    '--json',
                    '--verbose=false',
                    '--reporters=default',
                    '--runTestsByPath',
                    testPath,
                    `--testNamePattern=^${currentTestName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`,
                ],
                DEADLINE_MS,
                { ...process.env, [CHILD_MARKER]: JSON.stringify([process.pid, testPath, currentTestName]) }
            )
            const result = JSON.parse(output)
            expect(result).toMatchObject({
                success: true,
                numFailedTests: 0,
                numPassedTests: 1,
                numPassedTestSuites: 1,
            })
            const assertions = result.testResults.flatMap(
                (suite: { assertionResults: { fullName: string; status: string; numPassingAsserts: number }[] }) =>
                    suite.assertionResults.filter((assertion) => assertion.fullName === currentTestName)
            )
            expect(assertions).toEqual([expect.objectContaining({ status: 'passed' })])
            expect(assertions[0].numPassingAsserts).toBeGreaterThan(0)
        },
        DEADLINE_MS + 5000
    )
}
