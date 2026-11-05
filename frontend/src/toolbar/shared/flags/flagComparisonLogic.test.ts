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
            outcome: 'fails',
            flagOverrides: userOverrides,
            secondCapture: () => Promise.reject(new Error('Cross-origin font')),
        },
        {
            outcome: 'succeeds with no earlier overrides',
            flagOverrides: undefined,
            secondCapture: () => Promise.resolve(new Blob(['on page'])),
        },
    ])("restores the user's overrides when the capture $outcome", async ({ flagOverrides, secondCapture }) => {
        persisted.$override_feature_flags = flagOverrides
        jest.mocked(captureElementScreenshot)
            .mockResolvedValueOnce(new Blob(['off']))
            .mockImplementationOnce(secondCapture)

        await expectLogic(logic, () => logic.actions.compareFlag(flag)).toFinishAllListeners()

        expect(persisted).toEqual({
            $override_feature_flags: flagOverrides,
            $override_feature_flag_payloads: userPayloads,
        })
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
