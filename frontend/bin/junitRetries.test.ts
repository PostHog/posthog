import { mkdtempSync, readFileSync, rmSync } from 'fs'
import { tmpdir } from 'os'
import { join } from 'path'

const JestJUnit = require('jest-junit')

describe('JUnit retry reports', () => {
    test.each([
        ['passed', [], undefined],
        ['passed', ['first attempt <failed>'], 'flakyFailure'],
        ['failed', ['first attempt <failed>'], 'rerunFailure'],
    ])('reports %s with retry evidence %j', (status, retryReasons, retryTag) => {
        const directory = mkdtempSync(join(tmpdir(), 'junit-retries-'))
        const originalEnvironment = process.env
        process.env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith('JEST_JUNIT_')))
        try {
            const reporter = new JestJUnit(
                { rootDir: directory },
                { outputDirectory: directory, outputName: 'junit.xml' }
            )
            reporter.onRunComplete(new Set(), {
                startTime: Date.now(),
                testResults: [
                    {
                        testFilePath: join(directory, 'example.test.js'),
                        perfStats: { start: Date.now(), end: Date.now() },
                        numFailingTests: status === 'failed' ? 1 : 0,
                        numPassingTests: status === 'passed' ? 1 : 0,
                        numPendingTests: 0,
                        testResults: [
                            {
                                ancestorTitles: ['example'],
                                title: 'retries',
                                duration: 1,
                                status,
                                retryReasons,
                                failureMessages: status === 'failed' ? ['final failure'] : [],
                            },
                        ],
                    },
                ],
            })
            const report = readFileSync(join(directory, 'junit.xml'), 'utf8')
            expect(report.match(/<testcase\s/g)).toHaveLength(1)
            expect(report.includes('<failure>')).toBe(status === 'failed')
            if (retryTag) {
                expect(report).toContain(`<${retryTag}>first attempt &lt;failed&gt;</${retryTag}>`)
            } else {
                expect(report).not.toMatch(/<(flaky|rerun)Failure>/)
            }
        } finally {
            process.env = originalEnvironment
            rmSync(directory, { recursive: true, force: true })
        }
    })
})
