import assert from 'node:assert/strict'
import { mkdtemp, mkdir, readFile, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { test } from 'node:test'

import { report } from './report.mjs'

test('an operational report requires matching successful work and retains recovered CI retries', async () => {
    for (const corruption of ['none', 'skip', 'retry', 'missing', 'different-id', 'wrong-file', 'recovered']) {
        const directory = `${await mkdtemp(join(tmpdir(), 'stagehand-report-'))}/`
        try {
            await mkdir(`${directory}results`)
            const rows = []
            for (let pair = -1; pair < 5; pair++) {
                for (const driver of ['playwright', 'stagehand']) {
                    const specs = Array.from({ length: 10 }, (_, index) => ({
                        title: `Flow ${index}`,
                        file:
                            driver === 'stagehand'
                                ? '.github/benchmarks/stagehand/stagehand.spec.ts'
                                : index < 9
                                  ? 'playwright/e2e/auth.spec.ts'
                                  : 'playwright/e2e/before-onboarding.spec.ts',
                        tests: [
                            {
                                expectedStatus: 'passed',
                                status: 'expected',
                                results: [{ status: 'passed', retry: 0, duration: 10 }],
                            },
                        ],
                    }))
                    if (pair === 0 && driver === 'stagehand') {
                        if (corruption === 'skip') specs[0].tests[0].status = 'skipped'
                        if (corruption === 'retry')
                            specs[0].tests[0].results.push({ status: 'passed', retry: 1, duration: 10 })
                        if (corruption === 'missing') specs.pop()
                        if (corruption === 'different-id') specs[0].title = 'Different flow'
                        if (corruption === 'wrong-file') specs[0].file = 'playwright/e2e/auth.spec.ts'
                        if (corruption === 'recovered') {
                            specs[0].tests[0].status = 'flaky'
                            specs[0].tests[0].results[0].status = 'failed'
                            specs[0].tests[0].results.push({ status: 'passed', retry: 1, duration: 10 })
                        }
                    }
                    await writeFile(
                        `${directory}results/${driver}-${pair}.json`,
                        JSON.stringify({ errors: [], stats: {}, suites: [{ title: 'file', specs, suites: [] }] })
                    )
                    rows.push({ driver, pair, warmup: pair < 0, exitCode: 0, wallMs: 100 })
                }
            }
            assert.equal(await report(directory, rows), ['none', 'recovered'].includes(corruption), corruption)
            if (corruption === 'recovered') {
                const result = JSON.parse(await readFile(`${directory}results/validated.json`, 'utf8'))
                assert.equal(result.clean, false)
                assert.equal(result.summaries.find((row) => row.driver === 'stagehand').retries, 1)
                assert.equal(result.summaries.find((row) => row.driver === 'stagehand').failedAttempts, 1)
            }
        } finally {
            await rm(directory, { recursive: true, force: true })
        }
    }
})
