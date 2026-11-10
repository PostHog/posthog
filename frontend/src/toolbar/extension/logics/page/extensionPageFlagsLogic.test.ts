import { waitFor } from '@testing-library/react'
import type { PostHog } from 'posthog-js'

import { initKeaTests } from '~/test/init'
import { flagsToolbarLogic } from '~/toolbar/shared/flags/flagsToolbarLogic'
import { toolbarConfigLogic } from '~/toolbar/shared/toolbarConfigLogic'
import { captureElementScreenshot } from '~/toolbar/shared/utils/screenshot'
import type { CombinedFeatureFlagAndValueType } from '~/types'

import type { PageAgentRequestMessage } from '../../messaging/pageAgentProtocol'
import { extensionPageFlagsLogic } from './extensionPageFlagsLogic'
import { jpegDataUrl } from './jpegDataUrl'

jest.mock('~/toolbar/shared/toolbarLogger', () => ({
    toolbarLogger: { debug: jest.fn(), info: jest.fn(), warn: jest.fn(), error: jest.fn() },
}))
// jsdom cannot rasterize a page or decode an image, and the real settle wait only measures DOM quiet time.
jest.mock('~/toolbar/shared/utils/screenshot', () => ({ captureElementScreenshot: jest.fn() }))
jest.mock('~/toolbar/shared/flags/flagComparison', () => ({
    ...jest.requireActual('~/toolbar/shared/flags/flagComparison'),
    waitForPageToSettle: jest.fn(() => Promise.resolve()),
}))
jest.mock('./jpegDataUrl', () => ({ jpegDataUrl: jest.fn((url: string) => Promise.resolve(`data:${url}`)) }))

// A comparison crosses several loaders and listeners, which a loaded CI runner can take longer than `waitFor`'s 1 s for.
const SLOW_RUNNER_TIMEOUT_MS = 4000

describe('extensionPageFlagsLogic', () => {
    let persisted: Record<string, unknown>
    let onOverride: () => void
    let logic: ReturnType<typeof extensionPageFlagsLogic.build>

    beforeEach(() => {
        persisted = { $override_feature_flags: {} }
        onOverride = () => {}
        const posthog = {
            get_property: (key: string) => persisted[key],
            onFeatureFlags: () => () => {},
            featureFlags: {
                getFlagVariants: () => ({}),
                overrideFeatureFlags: (options: { flags: unknown }) => {
                    persisted.$override_feature_flags = options.flags
                    onOverride()
                },
            },
        } as unknown as PostHog
        jest.spyOn(window, 'postMessage').mockImplementation(() => undefined)
        jest.mocked(captureElementScreenshot).mockReset()
        let capture = 0
        URL.createObjectURL = jest.fn(() => `blob:capture-${capture++}`)
        URL.revokeObjectURL = jest.fn()

        initKeaTests()
        toolbarConfigLogic
            .build({
                apiURL: 'http://localhost',
                accessToken: 'token',
                clientId: 'client',
                posthog,
                source: 'extension',
            })
            .mount()
        logic = extensionPageFlagsLogic()
        logic.mount()
        flagsToolbarLogic.actions.getUserFlagsSuccess([
            { feature_flag: { key: 'new-checkout', id: 1 }, value: false } as CombinedFeatureFlagAndValueType,
        ])
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    test('refuses a flag change from another panel while it compares, and lets that panel send again', async () => {
        let releaseCapture: (blob: Blob) => void = () => {}
        const captureStarted = new Promise<void>((started) => {
            jest.mocked(captureElementScreenshot).mockImplementationOnce(() => {
                started()
                return new Promise((resolve) => (releaseCapture = resolve))
            })
        })
        logic.actions.handleCommand({ type: 'compare-flag', flagKey: 'new-checkout' })
        const revision = logic.values.pageState.mutationRevision

        logic.actions.handleCommand({ type: 'set-flag-override', flagKey: 'new-checkout', value: true })

        expect(logic.values.pageState).toMatchObject({
            comparingFlagKey: 'new-checkout',
            mutationRevision: revision + 1,
        })
        expect(persisted.$override_feature_flags).toEqual({ 'new-checkout': false })

        jest.mocked(captureElementScreenshot).mockResolvedValue(new Blob(['on']))
        await captureStarted
        releaseCapture(new Blob(['off']))
        await waitFor(() => expect(logic.values.comparison).not.toBeNull(), { timeout: SLOW_RUNNER_TIMEOUT_MS })
        expect(logic.values.pageState.comparingFlagKey).toBeNull()
        expect(persisted.$override_feature_flags).toEqual({})

        // The bridge counts only the changes it applied, so its first one carries a revision the panel already saw.
        const revisionAfterComparison = logic.values.pageState.mutationRevision
        logic.actions.setFlagMutationStatus({ pending: false, error: null, revision: 1 })
        expect(logic.values.pageState.mutationRevision).toBeGreaterThan(revisionAfterComparison)
    })

    test('hands the panel the captures as data URLs, and clears them when the panel closes the comparison', async () => {
        jest.mocked(captureElementScreenshot).mockResolvedValue(new Blob(['page']))

        logic.actions.handleCommand({ type: 'compare-flag', flagKey: 'new-checkout' })
        await waitFor(() => expect(logic.values.comparison).not.toBeNull(), { timeout: SLOW_RUNNER_TIMEOUT_MS })

        expect(logic.values.comparison?.captures.map(({ url }) => url)).toEqual([
            'data:blob:capture-0',
            'data:blob:capture-1',
        ])
        const unloadRestores = jest
            .mocked(window.postMessage)
            .mock.calls.map(([message]) => (message as PageAgentRequestMessage).request)
            .filter((request) => request?.method === 'restore-flags-on-unload')
        expect(unloadRestores).toEqual([
            { method: 'restore-flags-on-unload', flags: {} },
            { method: 'restore-flags-on-unload', flags: null },
        ])

        logic.actions.handleCommand({ type: 'close-flag-comparison' })
        expect(logic.values.comparison).toBeNull()
    })

    test('keeps the unload restore and shows no captures when the page refuses the restore', async () => {
        jest.mocked(captureElementScreenshot).mockResolvedValue(new Blob(['page']))
        onOverride = () => logic.actions.setFlagMutationStatus({ ...logic.values.flagMutationStatus, pending: true })

        logic.actions.handleCommand({ type: 'compare-flag', flagKey: 'new-checkout' })
        await waitFor(() => expect(logic.values.runningComparisonFlagKey).toBeNull(), {
            timeout: SLOW_RUNNER_TIMEOUT_MS,
        })
        logic.actions.setFlagMutationStatus({ pending: false, error: "The page didn't answer.", revision: 1 })

        await waitFor(() => expect(logic.values.pageState.comparingFlagKey).toBeNull(), {
            timeout: SLOW_RUNNER_TIMEOUT_MS,
        })
        expect(logic.values.pageState).toMatchObject({
            mutationError: "The page didn't answer.",
            comparisonError: null,
        })
        expect(logic.values.comparison).toBeNull()
        const unloadRestores = jest
            .mocked(window.postMessage)
            .mock.calls.map(([message]) => (message as PageAgentRequestMessage).request)
            .filter((request) => request?.method === 'restore-flags-on-unload')
        expect(unloadRestores).toEqual([{ method: 'restore-flags-on-unload', flags: {} }])
    })

    test.each([
        {
            failure: 'the capture fails',
            arrange: () => jest.mocked(captureElementScreenshot).mockRejectedValue(new Error('Cross-origin font')),
            reason: 'capture_failed',
        },
        {
            failure: 'the data URL conversion fails',
            arrange: () => {
                jest.mocked(captureElementScreenshot).mockResolvedValue(new Blob(['page']))
                jest.mocked(jpegDataUrl).mockRejectedValueOnce(new Error('decode'))
            },
            reason: 'capture_failed',
        },
        {
            failure: 'the captures are too large for one port message',
            arrange: () => {
                jest.mocked(captureElementScreenshot).mockResolvedValue(new Blob(['page']))
                const halfTheLimit = 'x'.repeat(30 * 1024 * 1024 + 1)
                jest.mocked(jpegDataUrl).mockResolvedValueOnce(halfTheLimit).mockResolvedValueOnce(halfTheLimit)
            },
            reason: 'captures_too_large',
        },
    ])('reports $reason and accepts flag changes again when $failure', async ({ arrange, reason }) => {
        arrange()

        logic.actions.handleCommand({ type: 'compare-flag', flagKey: 'new-checkout' })
        await waitFor(() => expect(logic.values.pageState.comparisonError).not.toBeNull(), {
            timeout: SLOW_RUNNER_TIMEOUT_MS,
        })

        expect(logic.values.pageState).toMatchObject({ comparingFlagKey: null, comparisonError: reason })
    })
})
