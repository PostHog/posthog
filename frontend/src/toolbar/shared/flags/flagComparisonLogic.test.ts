import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'
import type { PostHog } from 'posthog-js'

import { initKeaTests } from '~/test/init'
import { toolbarLogic } from '~/toolbar/shared/bar/toolbarLogic'
import { flagComparisonLogic } from '~/toolbar/shared/flags/flagComparisonLogic'
import type { FlagInfo } from '~/toolbar/shared/flags/flagInfo'
import { toolbarConfigLogic } from '~/toolbar/shared/toolbarConfigLogic'
import { toolbarPosthogJS } from '~/toolbar/shared/toolbarPosthogJS'
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

const multivariateFlag: FlagInfo = {
    ...flag,
    variants: [
        { key: 'control', name: null, rolloutPercentage: 50 },
        { key: 'test', name: null, rolloutPercentage: 50 },
    ],
}

function failureReasons(): unknown[] {
    return jest
        .mocked(toolbarPosthogJS.capture)
        .mock.calls.filter(([event]) => event === 'toolbar feature flag comparison failed')
        .map(([, properties]) => properties?.reason)
}

describe('flagComparisonLogic', () => {
    let persisted: Record<string, unknown>
    let flagWrites: unknown[]
    let logic: ReturnType<typeof flagComparisonLogic.build>
    let unmountMenu: () => void
    let posthog: PostHog

    function mountLogics(source?: 'extension'): void {
        initKeaTests()
        toolbarConfigLogic.build({ apiURL: 'http://localhost', posthog, source }).mount()
        logic = flagComparisonLogic()
        unmountMenu = logic.mount()
    }

    beforeEach(() => {
        persisted = {
            $override_feature_flags: userOverrides,
            $override_feature_flag_payloads: userPayloads,
        }
        flagWrites = []
        posthog = {
            get_property: (key: string) => persisted[key],
            featureFlags: {
                overrideFeatureFlags: (options: { flags?: unknown; payloads?: unknown }) => {
                    if ('flags' in options) {
                        flagWrites.push(options.flags)
                        persisted.$override_feature_flags = options.flags === false ? undefined : options.flags
                    }
                    if ('payloads' in options) {
                        persisted.$override_feature_flag_payloads = options.payloads
                    }
                },
            },
        } as unknown as PostHog
        jest.spyOn(toolbarPosthogJS, 'capture').mockImplementation(() => undefined)
        let urlCount = 0
        URL.createObjectURL = jest.fn(() => `blob:capture-${urlCount++}`)
        URL.revokeObjectURL = jest.fn()

        mountLogics()
    })

    test.each([
        {
            outcome: 'restores the overrides when the capture fails',
            flagOverrides: userOverrides,
            secondCapture: () => Promise.reject(new Error('Cross-origin font')),
            expectedOverrides: userOverrides,
            expectsComparison: false,
            revokedUrls: ['blob:capture-0'],
            failureReasons: ['capture_failed'],
        },
        {
            outcome: 'restores no overrides when there were none',
            flagOverrides: undefined,
            secondCapture: () => Promise.resolve(new Blob(['on page'])),
            expectedOverrides: undefined,
            expectsComparison: true,
            revokedUrls: [],
            failureReasons: [],
        },
        {
            outcome: 'keeps a logout that cleared the overrides during the capture',
            flagOverrides: userOverrides,
            secondCapture: () => {
                persisted.$override_feature_flags = undefined
                return Promise.resolve(new Blob(['on page']))
            },
            expectedOverrides: undefined,
            expectsComparison: false,
            revokedUrls: ['blob:capture-0'],
            failureReasons: ['overrides_changed'],
        },
    ])('$outcome', async (row) => {
        const { flagOverrides, secondCapture, expectedOverrides, expectsComparison, revokedUrls } = row
        persisted.$override_feature_flags = flagOverrides
        jest.mocked(captureElementScreenshot)
            .mockResolvedValueOnce(new Blob(['off']))
            .mockImplementationOnce(secondCapture)

        await expectLogic(logic, () => logic.actions.compareFlag(flag)).toFinishAllListeners()

        expect(persisted).toEqual({
            $override_feature_flags: expectedOverrides,
            $override_feature_flag_payloads: userPayloads,
        })
        expect(logic.values.comparison !== null).toBe(expectsComparison)
        expect(jest.mocked(URL.revokeObjectURL).mock.calls.map(([url]) => url)).toEqual(revokedUrls)
        expect(failureReasons()).toEqual(row.failureReasons)
    })

    test('captures each variant of a multivariate flag and compares each with off', async () => {
        jest.mocked(captureElementScreenshot)
            .mockResolvedValueOnce(new Blob(['aaa']))
            .mockResolvedValueOnce(new Blob(['aaa']))
            .mockResolvedValueOnce(new Blob(['bbb']))

        await expectLogic(logic, () => logic.actions.compareFlag(multivariateFlag)).toFinishAllListeners()

        expect(flagWrites).toEqual([
            { ...userOverrides, [flag.key]: false },
            { ...userOverrides, [flag.key]: 'control' },
            { ...userOverrides, [flag.key]: 'test' },
            userOverrides,
        ])
        expect(logic.values.comparison?.captures.map((capture) => capture.sameAsOff)).toEqual([true, true, false])
        expect(logic.values.comparison?.identical).toBe(false)
        expect(logic.values.afterCapture?.value).toEqual('control')

        logic.actions.setAfterValue('test')
        expect(logic.values.afterCapture?.value).toEqual('test')
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

    test('restores the overrides when a capture never finishes, and starts no capture until it ends', async () => {
        let releaseStalledCapture: (blob: Blob) => void = () => {}
        jest.useFakeTimers()
        try {
            jest.mocked(captureElementScreenshot)
                .mockResolvedValueOnce(new Blob(['off']))
                .mockReturnValueOnce(new Promise((resolve) => (releaseStalledCapture = resolve)))

            logic.actions.compareFlag(flag)
            await jest.advanceTimersByTimeAsync(20000)

            expect(persisted.$override_feature_flags).toEqual(userOverrides)
            expect(logic.values.comparingFlagKey).toBeNull()

            const writesBeforeRetry = flagWrites.length
            logic.actions.compareFlag(flag)
            await jest.advanceTimersByTimeAsync(0)
            expect(captureElementScreenshot).toHaveBeenCalledTimes(2)
            expect(flagWrites).toHaveLength(writesBeforeRetry)
            expect(failureReasons()).toEqual(['capture_timeout', 'capture_still_running'])
        } finally {
            releaseStalledCapture(new Blob(['late']))
            jest.useRealTimers()
        }
        await expectLogic(logic).toFinishAllListeners()
    })

    test.each([
        { form: 'floating toolbar', source: undefined, expectedMenu: 'flags' },
        // The extension's panel shows the comparison, and a menu in its content script would turn off its heatmap.
        { form: 'extension', source: 'extension' as const, expectedMenu: 'none' },
    ])(
        'shows the comparison when the flags menu closes during the capture, in the $form',
        async ({ source, expectedMenu }) => {
            mountLogics(source)
            jest.mocked(captureElementScreenshot).mockResolvedValue(new Blob(['page']))

            logic.actions.compareFlag(flag)
            unmountMenu()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.comparison).toMatchObject({ flagKey: flag.key, identical: true })
            expect(toolbarLogic.values.visibleMenu).toEqual(expectedMenu)
        }
    )
})
