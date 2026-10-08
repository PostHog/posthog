import assert from 'node:assert/strict'
import { spawn, execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { cpus, loadavg } from 'node:os'
import { performance } from 'node:perf_hooks'
import { fileURLToPath } from 'node:url'

assert.equal(process.env.CI, 'true', 'Browser measurements run in CI only')
const directory = fileURLToPath(new URL('.', import.meta.url))
const repositoryRequire = createRequire(`${process.cwd()}/playwright/package.json`)
const executablePath = repositoryRequire('@playwright/test').chromium.executablePath()
const diagnostic = process.argv.includes('--diagnostic')
await mkdir(`${directory}results`, { recursive: true })
const measurements = []
const containerIds = execFileSync('docker', ['ps', '--quiet'], { encoding: 'utf8' }).trim().split('\n').filter(Boolean)
const manifest = JSON.parse(await readFile(`${directory}package.json`, 'utf8'))
const metadata = {
    commit: execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim(),
    run: process.env.GITHUB_RUN_ID,
    attempt: process.env.GITHUB_RUN_ATTEMPT,
    runner: process.env.RUNNER_NAME,
    repeat: process.env.BENCHMARK_REPEAT,
    node: process.version,
    cores: cpus().length,
    packages: manifest.dependencies,
    playwrightVersion: repositoryRequire('@playwright/test/package.json').version,
    chromiumVersion: execFileSync(executablePath, ['--version'], { encoding: 'utf8' }).trim(),
    chromiumHash: createHash('sha256')
        .update(await readFile(executablePath))
        .digest('hex'),
    setupSeconds: (Date.now() - Number(process.env.BENCHMARK_SETUP_STARTED_AT)) / 1000,
    stagehandInstallSeconds: Number(process.env.BENCHMARK_STAGEHAND_INSTALL_SECONDS),
    containerImages: containerIds.length
        ? execFileSync('docker', ['inspect', '--format', '{{.Name}} {{.Image}}', ...containerIds], { encoding: 'utf8' })
              .trim()
              .split('\n')
              .sort()
        : [],
    fixtureHashes: Object.fromEntries(
        await Promise.all(
            [
                'playwright/e2e/auth.spec.ts',
                'playwright/e2e/before-onboarding.spec.ts',
                '.github/benchmarks/stagehand/stagehand.spec.ts',
            ].map(async (path) => [
                path,
                createHash('sha256')
                    .update(await readFile(path))
                    .digest('hex'),
            ])
        )
    ),
    lockHash: createHash('sha256')
        .update(await readFile(`${directory}pnpm-lock.yaml`))
        .digest('hex'),
    schemaCacheHit: process.env.BENCHMARK_SCHEMA_CACHE_HIT,
    packageCacheHit: process.env.BENCHMARK_PACKAGE_CACHE_HIT,
}
if (!diagnostic) await writeFile(`${directory}results/metadata.json`, JSON.stringify(metadata, null, 2))
for (let pair = diagnostic ? 0 : -1; pair < (diagnostic ? 1 : 5); pair++) {
    const drivers =
        (pair + Number(process.env.BENCHMARK_REPEAT)) % 2 === 0
            ? ['stagehand', 'playwright']
            : ['playwright', 'stagehand']
    for (const driver of drivers) {
        const started = performance.now()
        const row = { driver, pair, warmup: pair < 0, loadBefore: loadavg() }
        row.exitCode = await new Promise((resolve, reject) => {
            const child = spawn(
                process.execPath,
                [
                    './playwright/node_modules/@playwright/test/cli.js',
                    'test',
                    '--config',
                    '.github/benchmarks/stagehand/playwright.config.ts',
                    '--workers',
                    '6',
                ],
                {
                    stdio: 'inherit',
                    env: {
                        ...process.env,
                        BENCHMARK_DRIVER: driver,
                        BENCHMARK_SAMPLE: diagnostic ? 'profile' : String(pair),
                        ...(diagnostic
                            ? { NODE_OPTIONS: `--cpu-prof --cpu-prof-dir=${directory}results/profile` }
                            : {}),
                    },
                }
            )
            child.once('error', reject)
            child.once('exit', (code) => resolve(code ?? 1))
        })
        row.wallMs = performance.now() - started
        row.loadAfter = loadavg()
        measurements.push(row)
        await writeFile(
            `${directory}results/${diagnostic ? 'diagnostics' : 'measurements'}.json`,
            JSON.stringify(measurements, null, 2)
        )
    }
    if (measurements.some((row) => row.exitCode !== 0)) break
    const reports = await Promise.all(
        drivers.map(async (driver) =>
            JSON.parse(await readFile(`${directory}results/${driver}-${diagnostic ? 'profile' : pair}.json`, 'utf8'))
        )
    )
    if (reports.some(({ stats }) => stats.expected !== 10 || stats.unexpected || stats.flaky || stats.skipped)) break
}
if (diagnostic) {
    if (measurements.some((row) => row.exitCode !== 0)) process.exitCode = 1
} else {
    const { report } = await import('./report.mjs')
    if (!(await report(directory, measurements))) process.exitCode = 1
}
