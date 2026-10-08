import assert from 'node:assert/strict'
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { test } from 'node:test'

import { report } from './report.mjs'

test('a speed report requires complete, matching, first-attempt successful work', async () => {
    for (const corruption of ['none', 'skip', 'retry', 'missing', 'different-id', 'wrong-file']) {
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
                    }
                    await writeFile(
                        `${directory}results/${driver}-${pair}.json`,
                        JSON.stringify({ errors: [], stats: {}, suites: [{ title: 'file', specs, suites: [] }] })
                    )
                    rows.push({ driver, pair, warmup: pair < 0, exitCode: 0, wallMs: 100 })
                }
            }
            assert.equal(await report(directory, rows), corruption === 'none', corruption)
        } finally {
            await rm(directory, { recursive: true, force: true })
        }
    }
})
