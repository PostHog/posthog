import path from 'node:path'

import { defineConfig } from '../../../playwright/node_modules/@playwright/test'
import original from '../../../playwright/playwright.config'

const driver = process.env.BENCHMARK_DRIVER
if (driver !== 'playwright' && driver !== 'stagehand') throw new Error('BENCHMARK_DRIVER must name an explicit driver')

export default defineConfig({
    ...original,
    testDir: '../../..',
    testMatch:
        driver === 'playwright'
            ? ['playwright/e2e/auth.spec.ts', 'playwright/e2e/before-onboarding.spec.ts']
            : ['.github/benchmarks/stagehand/stagehand.spec.ts'],
    reporter: [
        ['json', { outputFile: path.join(__dirname, 'results', `${driver}-${process.env.BENCHMARK_SAMPLE}.json`) }],
        ['list'],
    ],
    outputDir: path.join(__dirname, 'results', `${driver}-${process.env.BENCHMARK_SAMPLE}-artifacts`),
    retries: 1,
    projects: [{ name: 'chromium', use: { ...original.projects![0].use, channel: 'chromium' } }],
})
