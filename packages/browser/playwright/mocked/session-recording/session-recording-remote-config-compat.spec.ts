/**
 * Cross-version compatibility test for session recording remote config.
 *
 * This test should be added to posthog-js at:
 *   packages/browser/playwright/mocked/session-recording/session-recording-remote-config-compat.spec.ts
 *
 * It exercises the scenario that caused the bug fixed in PR #3213:
 *   - Old SDK versions (pre-1.359.0) persist session recording config WITHOUT a `cache_timestamp` field
 *   - New recorder extension must treat missing `cache_timestamp` as fresh (Date.now()), not stale (0)
 *   - If treated as stale, the config is deleted before recording can start, causing a ~90% drop in recordings
 *
 * The existing compat tests run the full mocked test suite with old array.js + new extensions,
 * but none of the session recording tests exercise the config persistence/caching flow.
 * They all start fresh from mocked remote config responses, never testing what happens when
 * config is loaded from localStorage persistence — which is the exact cross-version boundary.
 */

import { expect, test, WindowWithPostHog } from '../utils/posthog-playwright-test-base'
import { start, waitForSessionRecordingToStart } from '../utils/setup'

const startOptions = {
    options: { session_recording: {} },
    flagsResponseOverrides: {
        sessionRecording: { endpoint: '/ses/' },
        capturePerformance: true,
        autocapture_opt_out: true,
        __preview_eager_load_replay: false,
    },
    url: './playground/cypress/index.html',
}

test.describe('Session recording - remote config cross-version compatibility', () => {
    test('recording starts when persisted config has no cache_timestamp (legacy SDK)', async ({ page, context }) => {
        // Step 1: Start recording normally so config gets persisted
        await page.waitingForNetworkCausedBy({
            urlPatternsToWaitFor: ['**/recorder.js*'],
            action: async () => {
                await start(startOptions, page, context)
            },
        })
        await waitForSessionRecordingToStart(page)

        // Step 2: Simulate what a legacy SDK (pre-1.359.0) would have persisted:
        // config object WITHOUT cache_timestamp field
        await page.evaluate(() => {
            const ph = (window as WindowWithPostHog).posthog
            // Get the current persisted config and strip cache_timestamp
            const currentConfig = ph?.get_property('$session_recording_remote_config')
            if (currentConfig) {
                const legacyConfig = { ...currentConfig }
                delete legacyConfig.cache_timestamp
                // Re-persist without cache_timestamp, simulating old SDK behavior
                ph?.persistence?.register({ $session_recording_remote_config: legacyConfig })
            }
        })

        // Step 3: Reload the page — new extensions will read persisted config
        await page.waitingForNetworkCausedBy({
            urlPatternsToWaitFor: ['**/recorder.js*'],
            action: async () => {
                await start({ ...startOptions, type: 'reload' }, page, page.context())
            },
        })

        // Step 4: Recording MUST start despite missing cache_timestamp
        // Before the fix (PR #3213), this would fail because:
        //   cache_timestamp ?? 0 → 0 → Date.now() - 0 > TTL → config treated as stale → deleted
        await waitForSessionRecordingToStart(page)

        // Verify recording is actually active by checking for snapshot events
        await page.resetCapturedEvents()
        const responsePromise = page.waitForResponse('**/ses/*')
        await page.locator('[data-cy-input]').type('hello posthog!')
        await responsePromise

        const capturedEvents = await page.capturedEvents()
        const snapshot = capturedEvents?.find((e: any) => e.event === '$snapshot')
        expect(snapshot).toBeDefined()

        // Verify recording status is active
        const recordingStatus = await page.evaluate(() => {
            const ph = (window as WindowWithPostHog).posthog
            return ph?.sessionRecording?.['status']
        })
        expect(recordingStatus).toEqual('active')
    })

    test('recording starts when persisted config has stale cache_timestamp after reload', async ({
        page,
        context,
    }) => {
        // Start recording normally
        await page.waitingForNetworkCausedBy({
            urlPatternsToWaitFor: ['**/recorder.js*'],
            action: async () => {
                await start(startOptions, page, context)
            },
        })
        await waitForSessionRecordingToStart(page)

        // Set cache_timestamp to 0 (epoch) — simulating what PR #3191 defaulted to
        await page.evaluate(() => {
            const ph = (window as WindowWithPostHog).posthog
            const currentConfig = ph?.get_property('$session_recording_remote_config')
            if (currentConfig) {
                ph?.persistence?.register({
                    $session_recording_remote_config: { ...currentConfig, cache_timestamp: 0 },
                })
            }
        })

        // Reload — the remote config mock will respond, so recording should recover
        // even though persisted config is "stale"
        await page.waitingForNetworkCausedBy({
            urlPatternsToWaitFor: ['**/recorder.js*'],
            action: async () => {
                await start({ ...startOptions, type: 'reload' }, page, page.context())
            },
        })
        await waitForSessionRecordingToStart(page)

        // Verify recording works
        await page.resetCapturedEvents()
        const responsePromise = page.waitForResponse('**/ses/*')
        await page.locator('[data-cy-input]').type('hello posthog!')
        await responsePromise

        const capturedEvents = await page.capturedEvents()
        const snapshot = capturedEvents?.find((e: any) => e.event === '$snapshot')
        expect(snapshot).toBeDefined()
    })

    test('recording persists cache_timestamp in config for cross-version safety', async ({ page, context }) => {
        // Verify that current SDK always persists cache_timestamp
        // so future versions can rely on it
        await page.waitingForNetworkCausedBy({
            urlPatternsToWaitFor: ['**/recorder.js*'],
            action: async () => {
                await start(startOptions, page, context)
            },
        })
        await waitForSessionRecordingToStart(page)

        const persistedConfig = await page.evaluate(() => {
            const ph = (window as WindowWithPostHog).posthog
            return ph?.get_property('$session_recording_remote_config')
        })

        expect(persistedConfig).toBeDefined()
        expect(persistedConfig.cache_timestamp).toBeDefined()
        expect(typeof persistedConfig.cache_timestamp).toEqual('number')
        expect(persistedConfig.cache_timestamp).toBeGreaterThan(0)
        // Should be recent (within last minute)
        expect(Date.now() - persistedConfig.cache_timestamp).toBeLessThan(60_000)
    })
})
