import { readFile, writeFile } from 'node:fs/promises'

function median(values) {
    const sorted = [...values].sort((a, b) => a - b)
    const middle = Math.floor(sorted.length / 2)
    return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2
}

function pairedInterval(ratios) {
    if (ratios.length !== 5) return null
    let seed = 42
    const samples = Array.from({ length: 2000 }, () =>
        median(
            Array.from({ length: ratios.length }, () => {
                seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0
                return ratios[Math.floor((seed / 2 ** 32) * ratios.length)]
            })
        )
    ).sort((a, b) => a - b)
    return [samples[49], samples[1949]]
}

function collect(suites, parents = [], depth = 0) {
    return suites.flatMap((suite) => [
        ...suite.specs.flatMap((spec) =>
            spec.tests.map((test) => ({
                id: [...parents, spec.title].join(' / '),
                file: spec.file,
                expected: test.expectedStatus,
                status: test.status,
                attempts: test.results.map((result) => ({
                    status: result.status,
                    duration: result.duration,
                    retry: result.retry,
                })),
            }))
        ),
        ...collect(suite.suites ?? [], depth === 0 ? parents : [...parents, suite.title], depth + 1),
    ])
}

export async function report(directory, measurements) {
    const outcomes = []
    const errors = []
    for (const row of measurements) {
        try {
            const json = JSON.parse(await readFile(`${directory}results/${row.driver}-${row.pair}.json`, 'utf8'))
            const tests = collect(json.suites)
            const expectedFiles =
                row.driver === 'playwright'
                    ? ['playwright/e2e/auth.spec.ts', 'playwright/e2e/before-onboarding.spec.ts']
                    : ['.github/benchmarks/stagehand/stagehand.spec.ts']
            const files = [...new Set(tests.map((test) => test.file))].sort()
            if (JSON.stringify(files) !== JSON.stringify(expectedFiles.sort()))
                errors.push(`${row.driver}/${row.pair}: unexpected spec files`)
            outcomes.push({ ...row, tests, stats: json.stats })
            if (
                json.errors.length ||
                !Number.isFinite(row.wallMs) ||
                row.wallMs <= 0 ||
                new Set(tests.map((test) => test.id)).size !== 10 ||
                row.exitCode !== 0 ||
                tests.length !== 10 ||
                tests.some(
                    (test) =>
                        test.expected !== 'passed' ||
                        test.status !== 'expected' ||
                        test.attempts.length !== 1 ||
                        test.attempts[0].status !== 'passed'
                )
            ) {
                errors.push(`${row.driver}/${row.pair}: incomplete, failing, retried or skipped tests`)
            }
        } catch (error) {
            errors.push(`${row.driver}/${row.pair}: ${String(error)}`)
        }
    }
    for (let pair = -1; pair < 5; pair++) {
        const rows = outcomes.filter((row) => row.pair === pair)
        if (rows.length !== 2) {
            errors.push(`Missing pair ${pair}`)
            continue
        }
        if (!rows.some((row) => row.driver === 'playwright') || !rows.some((row) => row.driver === 'stagehand'))
            errors.push(`Missing driver in pair ${pair}`)
        if (
            JSON.stringify(rows[0].tests.map((test) => test.id).sort()) !==
            JSON.stringify(rows[1].tests.map((test) => test.id).sort())
        )
            errors.push(`Test IDs differ in pair ${pair}`)
    }
    const measured = outcomes.filter((row) => !row.warmup)
    const summaries = ['playwright', 'stagehand'].map((driver) => {
        const rows = measured.filter((row) => row.driver === driver)
        const durations = rows.map((row) => row.wallMs / 1000)
        return {
            driver,
            samples: durations.length,
            medianSeconds: durations.length ? median(durations) : null,
            rangeSeconds: durations.length ? [Math.min(...durations), Math.max(...durations)] : null,
            failures: outcomes
                .filter((row) => row.driver === driver)
                .flatMap((row) => row.tests)
                .filter((test) => test.status !== 'expected').length,
            retries: outcomes
                .filter((row) => row.driver === driver)
                .flatMap((row) => row.tests)
                .reduce((sum, test) => sum + Math.max(0, test.attempts.length - 1), 0),
        }
    })
    const ratios = Array.from({ length: 5 }, (_, pair) => {
        const pw = measured.find((row) => row.driver === 'playwright' && row.pair === pair)
        const sh = measured.find((row) => row.driver === 'stagehand' && row.pair === pair)
        return pw && sh ? sh.wallMs / pw.wallMs : null
    }).filter((ratio) => ratio !== null)
    const result = {
        valid: errors.length === 0,
        errors,
        summaries,
        pairedRatios: ratios,
        ratioInterval: pairedInterval(ratios),
        outcomes,
    }
    await writeFile(`${directory}results/validated.json`, JSON.stringify(result, null, 2))
    const md = [
        '# Stagehand on real PostHog E2E flows',
        '',
        `Validation: ${result.valid ? 'passed for 10 ported scenarios' : 'FAILED; no speed comparison is valid'}.`,
        '',
        '| Driver | Measured passes | Median test command seconds | Min/max seconds | Failures | Retries |',
        '| --- | --- | --- | --- | --- | --- |',
        ...summaries.map(
            (row) =>
                `| ${row.driver} | ${row.samples} | ${row.medianSeconds?.toFixed(2) ?? 'unavailable'} | ${row.rangeSeconds?.map((value) => value.toFixed(2)).join(' / ') ?? 'unavailable'} | ${row.failures} | ${row.retries} |`
        ),
        '',
        'This is a native Stagehand port of the auth and pre-onboarding specs. Playwright still supplies the runner, retrying value assertions and API setup.',
        'It does not establish backward compatibility or whole-suite savings. Five within-job pairs share a host and stack; independent CI jobs are needed before choosing a winner.',
        'Setup and added installs remain in CI step timestamps. The shared setup runs once; do not attribute the full experiment job to either driver.',
        'Dollar savings are unmeasured. Inspect validated.json, original JSON reports, metadata and process diagnostics before interpreting durations.',
        `Paired Stagehand / Playwright ratio interval: ${result.ratioInterval?.map((value) => value.toFixed(3)).join(' / ') ?? 'unavailable'}. This resamples pairs within one host.`,
        ...errors.map((error) => `- ${error}`),
        '',
    ].join('\n')
    await writeFile(`${directory}results/summary.md`, md)
    console.log(md)
    return result.valid
}
