import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { describe, it } from 'node:test'

import { renderReports } from './render-depot-migration-report.mjs'

describe('Depot migration report renderer', () => {
    it('makes PR-controlled report content inert', () => {
        const root = fs.mkdtempSync(path.join(os.tmpdir(), 'depot-migration-report-'))
        const inputDir = path.join(root, 'input')
        const outputDir = path.join(root, 'output')
        fs.mkdirSync(inputDir)
        fs.writeFileSync(
            path.join(inputDir, 'django-migration-sql.json'),
            JSON.stringify({
                version: 1,
                migrations: [
                    {
                        path: 'posthog/migrations/1234_safe.py',
                        sql: 'SELECT 1;\n```\n<img src=x onerror=alert(1)>\n@posthog/security',
                    },
                ],
            })
        )
        fs.writeFileSync(
            path.join(inputDir, 'django-migration-risk.json'),
            JSON.stringify({
                version: 1,
                exit_code: 1,
                analysis: {
                    summary: { safe: 0, needs_review: 0, blocked: 1 },
                    max_level: 'Blocked',
                    migrations: [
                        {
                            label: '</summary><img src=x> @posthog/security',
                            level: 'Blocked',
                            file_path: 'posthog/migrations/1234_safe.py',
                        },
                    ],
                },
            })
        )
        fs.writeFileSync(
            path.join(inputDir, 'ch-migration-sql.json'),
            JSON.stringify({
                version: 1,
                count: 1,
                environments: ['unset', 'US', 'EU', 'DEV'].map((label) => ({
                    label,
                    output: '```\n</details><img src=x>\n@posthog/security',
                })),
            })
        )

        renderReports({
            inputDir,
            outputDir,
            repository: 'PostHog/posthog',
            headSha: '0123456789abcdef0123456789abcdef01234567',
            now: new Date('2026-09-21T12:15:00Z'),
        })

        for (const file of ['django-migration-sql.md', 'django-migration-risk.md', 'ch-migration-sql.md']) {
            const rendered = fs.readFileSync(path.join(outputDir, file), 'utf8')
            assert.doesNotMatch(rendered, /<img|<\/details>|<\/summary>|@posthog\/security/)
        }
        assert.match(fs.readFileSync(path.join(outputDir, 'django-migration-sql.md'), 'utf8'), /^    ```$/m)
        assert.match(fs.readFileSync(path.join(outputDir, 'django-migration-risk.md'), 'utf8'), /&lt;\/summary&gt;/)
    })
})
