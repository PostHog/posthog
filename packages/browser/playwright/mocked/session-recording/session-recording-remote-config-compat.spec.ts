/**
 * Exercises the reload path where remote config is delayed and the recorder
 * must bootstrap from persisted config. In compat mode (old array.js + new
 * recorder) this catches cross-version persistence format mismatches like
 * the cache_timestamp bug (PR #3213).
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
    test('recording starts and session persists when remote config is delayed on reload', async ({
        page,
        context,
    }) => {
        // First load — remote config responds instantly, SDK persists config
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

        // Verify recording works on first load
        await page.resetCapturedEvents()
        await page.waitingForNetworkCausedBy({
            urlPatternsToWaitFor: ['**/ses/*'],
            action: async () => {
                await page.locator('[data-cy-input]').type('hello posthog!')
            },
        })

        // Hold the remote config response on reload so the recorder must
        // bootstrap from persisted config written during the first load.
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

        // Reload — SDK must start recording from persisted config alone
        await page.waitingForNetworkCausedBy({
            urlPatternsToWaitFor: ['**/recorder.js*'],
            action: async () => {
                await page.reload()
            },
        })

        await waitForSessionRecordingToStart(page)

        // Session ID must survive the reload
        const reloadedSessionId = await page.evaluate(() => {
            const ph = (window as WindowWithPostHog).posthog
            return ph?.get_session_id()
        })
        expect(reloadedSessionId).toEqual(firstSessionId)

        // Verify snapshot events are tagged with the same session
        await page.resetCapturedEvents()
        const responsePromise = page.waitForResponse('**/ses/*')
        await page.locator('[data-cy-input]').type('hello posthog!')
        await responsePromise

        const capturedEvents = await page.capturedEvents()
        const snapshot = capturedEvents?.find((e: any) => e.event === '$snapshot')
        expect(snapshot).toBeDefined()
        expect(snapshot!['properties']['$session_id']).toEqual(firstSessionId)

        resolveConfigResponse?.()
        await page.unroute(/\/array\/[^/]+\/config(\?|$)/)
    })
})
