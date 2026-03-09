/**
 * Cross-version compatibility test for session recording remote config.
 *
 * This test should be added to posthog-js at:
 *   packages/browser/playwright/mocked/session-recording/session-recording-remote-config-compat.spec.ts
 *
 * The existing session recording tests all start fresh — the mocked remote config
 * responds instantly, so the recorder never has to rely on persisted config.
 * In real-world cross-version scenarios:
 *   1. Old SDK (array.js) persists recording config on first page load
 *   2. On reload, old SDK starts loading but remote config hasn't arrived yet
 *   3. New lazy recorder loads and reads persisted config to start recording early
 *   4. If the new recorder mishandles fields the old SDK didn't persist, recording breaks
 *
 * This test exercises that path by delaying the remote config response on reload,
 * forcing the recorder to bootstrap from persisted config written by the old SDK.
 * When run in compat mode (old array.js + new recorder), this naturally catches
 * cross-version persistence format incompatibilities like the cache_timestamp bug
 * (PR #3213).
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

test.describe('Session recording - remote config reload with persisted config', () => {
    test('recording starts from persisted config when remote config is delayed on reload', async ({
        page,
        context,
    }) => {
        // Step 1: Normal first page load — remote config responds instantly,
        // SDK persists recording config to localStorage
        await page.waitingForNetworkCausedBy({
            urlPatternsToWaitFor: ['**/recorder.js*'],
            action: async () => {
                await start(startOptions, page, context)
            },
        })
        await waitForSessionRecordingToStart(page)

        // Verify recording works on first load
        await page.resetCapturedEvents()
        await page.waitingForNetworkCausedBy({
            urlPatternsToWaitFor: ['**/ses/*'],
            action: async () => {
                await page.locator('[data-cy-input]').type('hello posthog!')
            },
        })

        // Step 2: Before reloading, intercept the remote config endpoint at the
        // page level (takes priority over context-level route set by start())
        // to delay the response. This forces the recorder to bootstrap from
        // persisted config written by the SDK on the first load.
        let resolveConfigResponse: (() => void) | undefined
        const configResponseReady = new Promise<void>((resolve) => {
            resolveConfigResponse = resolve
        })

        await page.route(/\/array\/[^/]+\/config(\?|$)/, async (route) => {
            // Hold the config response — don't fulfill until we say so
            await configResponseReady
            await route.fulfill({
                status: 200,
                contentType: 'application/json',
                body: JSON.stringify({
                    ...startOptions.flagsResponseOverrides,
                    featureFlags: {},
                    featureFlagPayloads: {},
                }),
            })
        })

        // Step 3: Reload the page. The old SDK core will initialize and try to
        // fetch remote config, but our page-level route holds the response.
        // The SDK should find persisted config and use it to load the recorder.
        await page.waitingForNetworkCausedBy({
            urlPatternsToWaitFor: ['**/recorder.js*'],
            action: async () => {
                await page.reload()
            },
        })

        // Step 4: Recording must start from persisted config even though
        // remote config hasn't responded yet.
        // In compat mode (old array.js), the persisted config won't have
        // cache_timestamp — the new recorder must handle this gracefully.
        await waitForSessionRecordingToStart(page)

        // Verify recording is actually capturing
        await page.resetCapturedEvents()
        const responsePromise = page.waitForResponse('**/ses/*')
        await page.locator('[data-cy-input]').type('hello posthog!')
        await responsePromise

        const capturedEvents = await page.capturedEvents()
        const snapshot = capturedEvents?.find((e: any) => e.event === '$snapshot')
        expect(snapshot).toBeDefined()

        // Now release the config response for clean teardown
        resolveConfigResponse?.()

        // Unroute our page-level override
        await page.unroute(/\/array\/[^/]+\/config(\?|$)/)
    })

    test('session continues across reload when remote config is delayed', async ({ page, context }) => {
        // First load — establish a session
        await page.waitingForNetworkCausedBy({
            urlPatternsToWaitFor: ['**/recorder.js*'],
            action: async () => {
                await start(startOptions, page, context)
            },
        })
        await waitForSessionRecordingToStart(page)

        const firstSessionId = await page.evaluate(() => {
            const ph = (window as WindowWithPostHog).posthog
            return ph?.get_session_id()
        })
        expect(firstSessionId).toBeTruthy()

        // Delay remote config on reload
        let resolveConfigResponse: (() => void) | undefined
        const configResponseReady = new Promise<void>((resolve) => {
            resolveConfigResponse = resolve
        })

        await page.route(/\/array\/[^/]+\/config(\?|$)/, async (route) => {
            await configResponseReady
            await route.fulfill({
                status: 200,
                contentType: 'application/json',
                body: JSON.stringify({
                    ...startOptions.flagsResponseOverrides,
                    featureFlags: {},
                    featureFlagPayloads: {},
                }),
            })
        })

        // Reload
        await page.waitingForNetworkCausedBy({
            urlPatternsToWaitFor: ['**/recorder.js*'],
            action: async () => {
                await page.reload()
            },
        })

        await waitForSessionRecordingToStart(page)

        // Session ID should persist across the reload
        const reloadedSessionId = await page.evaluate(() => {
            const ph = (window as WindowWithPostHog).posthog
            return ph?.get_session_id()
        })
        expect(reloadedSessionId).toEqual(firstSessionId)

        // Verify recording captures to the same session
        await page.resetCapturedEvents()
        const responsePromise = page.waitForResponse('**/ses/*')
        await page.locator('[data-cy-input]').type('hello posthog!')
        await responsePromise

        const capturedEvents = await page.capturedEvents()
        const snapshot = capturedEvents?.find((e: any) => e.event === '$snapshot')
        expect(snapshot).toBeDefined()
        expect(snapshot!['properties']['$session_id']).toEqual(firstSessionId)

        // Clean up
        resolveConfigResponse?.()
        await page.unroute(/\/array\/[^/]+\/config(\?|$)/)
    })
})
