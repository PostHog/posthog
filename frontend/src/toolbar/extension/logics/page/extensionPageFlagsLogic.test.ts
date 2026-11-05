import { waitFor } from '@testing-library/react'
import type { PostHog } from 'posthog-js'

import { initKeaTests } from '~/test/init'
import { flagsToolbarLogic } from '~/toolbar/shared/flags/flagsToolbarLogic'
import { toolbarConfigLogic } from '~/toolbar/shared/toolbarConfigLogic'
import { captureElementScreenshot } from '~/toolbar/shared/utils/screenshot'
import type { CombinedFeatureFlagAndValueType } from '~/types'

import { extensionPageFlagsLogic } from './extensionPageFlagsLogic'

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

describe('extensionPageFlagsLogic', () => {
    let persisted: Record<string, unknown>
    let logic: ReturnType<typeof extensionPageFlagsLogic.build>

    beforeEach(() => {
        persisted = { $override_feature_flags: {} }
        const posthog = {
            get_property: (key: string) => persisted[key],
            onFeatureFlags: () => () => {},
            featureFlags: {
                getFlagVariants: () => ({}),
                overrideFeatureFlags: (options: { flags: unknown }) => {
                    persisted.$override_feature_flags = options.flags
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
            .build({ apiURL: 'http://localhost', accessToken: 'token', clientId: 'client', posthog })
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
        jest.mocked(captureElementScreenshot).mockImplementationOnce(
            () => new Promise((resolve) => (releaseCapture = resolve))
        )
        logic.actions.handleCommand({ type: 'compare-flag', flagKey: 'new-checkout' })
        const revision = logic.values.pageState.mutationRevision

        logic.actions.handleCommand({ type: 'set-flag-override', flagKey: 'new-checkout', value: true })

        expect(logic.values.pageState).toMatchObject({
            comparingFlagKey: 'new-checkout',
            mutationRevision: revision + 1,
        })
        expect(persisted.$override_feature_flags).toEqual({ 'new-checkout': false })

        jest.mocked(captureElementScreenshot).mockResolvedValue(new Blob(['on']))
        await waitFor(() => expect(captureElementScreenshot).toHaveBeenCalled())
        releaseCapture(new Blob(['off']))
        await waitFor(() => expect(logic.values.comparison).not.toBeNull())
        expect(persisted.$override_feature_flags).toEqual({})
    })

    test('hands the panel the captures as data URLs, and clears them when the panel closes the comparison', async () => {
        jest.mocked(captureElementScreenshot).mockResolvedValue(new Blob(['page']))

        logic.actions.handleCommand({ type: 'compare-flag', flagKey: 'new-checkout' })
        await waitFor(() => expect(logic.values.pageState.comparingFlagKey).toBeNull())

        expect(logic.values.comparison?.captures.map(({ url }) => url)).toEqual([
            'data:blob:capture-0',
            'data:blob:capture-1',
        ])

        logic.actions.handleCommand({ type: 'close-flag-comparison' })
        expect(logic.values.comparison).toBeNull()
    })
})
