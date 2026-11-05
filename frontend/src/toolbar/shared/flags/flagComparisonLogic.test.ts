import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'
import type { PostHog } from 'posthog-js'

import { initKeaTests } from '~/test/init'
import { toolbarLogic } from '~/toolbar/shared/bar/toolbarLogic'
import { flagComparisonLogic } from '~/toolbar/shared/flags/flagComparisonLogic'
import type { FlagInfo } from '~/toolbar/shared/flags/flagInfo'
import { toolbarConfigLogic } from '~/toolbar/shared/toolbarConfigLogic'
import { captureElementScreenshot } from '~/toolbar/shared/utils/screenshot'

jest.mock('~/toolbar/shared/toolbarLogger', () => ({
    toolbarLogger: { debug: jest.fn(), info: jest.fn(), warn: jest.fn(), error: jest.fn() },
}))
// jsdom cannot rasterize a page, and the real settle wait only measures DOM quiet time.
jest.mock('~/toolbar/shared/utils/screenshot', () => ({ captureElementScreenshot: jest.fn() }))
jest.mock('~/toolbar/shared/flags/flagComparison', () => ({
    ...jest.requireActual('~/toolbar/shared/flags/flagComparison'),
    waitForPageToSettle: jest.fn(() => Promise.resolve()),
}))

const flag: FlagInfo = {
    key: 'new-checkout',
    id: 1,
    value: false,
    currentValue: false,
    hasOverride: false,
    variants: [],
    payloadOverride: null,
}

const userOverrides = { 'other-flag': 'test' }
const userPayloads = { 'other-flag': { color: 'blue' } }

describe('flagComparisonLogic', () => {
    let persisted: Record<string, unknown>
    let logic: ReturnType<typeof flagComparisonLogic.build>
    let unmountMenu: () => void

    beforeEach(() => {
        persisted = {
            $override_feature_flags: userOverrides,
            $override_feature_flag_payloads: userPayloads,
        }
        const posthog = {
            get_property: (key: string) => persisted[key],
            featureFlags: {
                overrideFeatureFlags: (options: { flags?: unknown; payloads?: unknown }) => {
                    if ('flags' in options) {
                        persisted.$override_feature_flags = options.flags === false ? undefined : options.flags
                    }
                    if ('payloads' in options) {
                        persisted.$override_feature_flag_payloads = options.payloads
                    }
                },
            },
        } as unknown as PostHog
        URL.createObjectURL = jest.fn(() => 'blob:capture')
        URL.revokeObjectURL = jest.fn()

        initKeaTests()
        toolbarConfigLogic.build({ apiURL: 'http://localhost', posthog }).mount()
        logic = flagComparisonLogic()
        unmountMenu = logic.mount()
    })

    test.each([
        {
            outcome: 'restores the overrides when the capture fails',
            flagOverrides: userOverrides,
            secondCapture: () => Promise.reject(new Error('Cross-origin font')),
            expectedOverrides: userOverrides,
        },
        {
            outcome: 'restores no overrides when there were none',
            flagOverrides: undefined,
            secondCapture: () => Promise.resolve(new Blob(['on page'])),
            expectedOverrides: undefined,
        },
        {
            outcome: 'keeps a logout that cleared the overrides during the capture',
            flagOverrides: userOverrides,
            secondCapture: () => {
                persisted.$override_feature_flags = undefined
                return Promise.resolve(new Blob(['on page']))
            },
            expectedOverrides: undefined,
        },
    ])('$outcome', async ({ flagOverrides, secondCapture, expectedOverrides }) => {
        persisted.$override_feature_flags = flagOverrides
        jest.mocked(captureElementScreenshot)
            .mockResolvedValueOnce(new Blob(['off']))
            .mockImplementationOnce(secondCapture)

        await expectLogic(logic, () => logic.actions.compareFlag(flag)).toFinishAllListeners()

        expect(persisted).toEqual({
            $override_feature_flags: expectedOverrides,
            $override_feature_flag_payloads: userPayloads,
        })
    })

    test('restores the overrides when the page unloads during a capture', async () => {
        let releaseCapture: (blob: Blob) => void = () => {}
        jest.mocked(captureElementScreenshot)
            .mockResolvedValueOnce(new Blob(['off']))
            .mockImplementationOnce(() => new Promise((resolve) => (releaseCapture = resolve)))

        logic.actions.compareFlag(flag)
        await waitFor(() => expect(captureElementScreenshot).toHaveBeenCalledTimes(2))
        expect(persisted.$override_feature_flags).toEqual({ ...userOverrides, [flag.key]: true })

        window.dispatchEvent(new Event('pagehide'))
        expect(persisted.$override_feature_flags).toEqual(userOverrides)

        releaseCapture(new Blob(['on page']))
        await expectLogic(logic).toFinishAllListeners()
    })

    test('restores the overrides when a capture never finishes', async () => {
        jest.useFakeTimers()
        try {
            jest.mocked(captureElementScreenshot)
                .mockResolvedValueOnce(new Blob(['off']))
                .mockReturnValueOnce(new Promise(() => {}))

            logic.actions.compareFlag(flag)
            await jest.advanceTimersByTimeAsync(20000)

            expect(persisted.$override_feature_flags).toEqual(userOverrides)
            expect(logic.values.comparingFlagKey).toBeNull()
        } finally {
            jest.useRealTimers()
        }
    })

    test('shows the comparison when the flags menu closes during the capture', async () => {
        jest.mocked(captureElementScreenshot).mockResolvedValue(new Blob(['page']))

        logic.actions.compareFlag(flag)
        unmountMenu()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.comparison?.flagKey).toEqual(flag.key)
        expect(toolbarLogic.values.visibleMenu).toEqual('flags')
    })
})
