import { forceGc, sampleMemory, summarise } from '../../utils/memory-sampler'
import type { MemorySample } from '../../utils/memory-sampler'
import { test } from '../../utils/playwright-test-base'

/**
 * Substring used to identify Playwright's Chromium renderers in `ps` output.
 * Playwright launches Chromium with `--user-data-dir=${TMPDIR}/playwright_chromiumdev_profile-XXXXXX`,
 * so this matches our test's renderer processes without picking up the host's
 * day-to-day Chrome / Electron / Steam-Helper renderers.
 */
const RENDERER_DISCRIMINATOR = 'playwright_chromiumdev'

/**
 * Idle-tab memory reproducer.
 *
 * Investigation under #57179 / #57221 / #57226 confirmed that PostHog tabs grow
 * to multi-GB renderer RSS while idle (no user interaction), even though V8 heap
 * stays small (~150 MB). The leak is invisible to JS-level probes — we have to
 * read renderer process RSS at the OS level.
 *
 * This test is the local reproducer. It currently runs **without strict
 * thresholds** so we can establish a baseline; once we have a candidate fix the
 * thresholds will be tightened.
 *
 * Skipped in CI: it idles for minutes per run, against a real dev stack. Run
 * locally with `pnpm --filter=@posthog/playwright exec playwright test
 * playwright/e2e/memory/idle-tab-memory.spec.ts --reporter=list`.
 */
test.describe('idle tab memory', () => {
    test.skip(!!process.env.CI, 'long idle test only runs locally')

    const TARGETS: Array<{ name: string; path: string }> = [
        { name: 'feature_flags-list', path: '/project/1/feature_flags?tab=overview' },
        { name: 'experiments-list', path: '/project/1/experiments' },
        { name: 'sql-editor', path: '/project/1/sql' },
    ]

    const idleSeconds = Number(process.env.IDLE_SECONDS || 300)
    const sampleEverySeconds = Number(process.env.SAMPLE_EVERY_SECONDS || 30)
    const expectedSamples = Math.floor(idleSeconds / sampleEverySeconds) + 2 // baseline + idle samples + final

    for (const target of TARGETS) {
        test(`${target.name} — ${idleSeconds}s idle should not balloon`, async ({ page }) => {
            test.setTimeout((idleSeconds + 60) * 1000)

            const discriminator = RENDERER_DISCRIMINATOR

            await page.goto(target.path)
            await page.waitForLoadState('networkidle').catch(() => undefined)
            // Belt-and-braces: give kea logics + any auto-loaders ~5s after networkidle
            // so the page is fully settled before baseline.
            await page.waitForTimeout(5000)

            await forceGc(page)
            const baseline = await sampleMemory(page, discriminator)

            const samples: MemorySample[] = [baseline]
            for (let i = 0; i < Math.floor(idleSeconds / sampleEverySeconds); i++) {
                await page.waitForTimeout(sampleEverySeconds * 1000)
                const s = await sampleMemory(page, discriminator)
                samples.push(s)
            }

            await forceGc(page)
            const finalSample = await sampleMemory(page, discriminator)
            samples.push(finalSample)

            const summary = summarise(samples)

            // No strict assertions yet — first job is to establish a baseline.
            // Once we have one, set thresholds via env or constants here.
            if (process.env.ASSERT_RSS_LIMIT_MB) {
                const limit = Number(process.env.ASSERT_RSS_LIMIT_MB)
                if (summary.rss_growth_mb !== null && summary.rss_growth_mb > limit) {
                    throw new Error(
                        `rss grew ${summary.rss_growth_mb} MB over ${summary.duration_s}s on ${target.name} (limit ${limit})`
                    )
                }
            }
            if (process.env.ASSERT_LISTENERS_LIMIT) {
                const limit = Number(process.env.ASSERT_LISTENERS_LIMIT)
                if (summary.listeners_growth > limit) {
                    throw new Error(
                        `listeners grew ${summary.listeners_growth} over ${summary.duration_s}s on ${target.name} (limit ${limit})`
                    )
                }
            }

            void expectedSamples
        })
    }
})
