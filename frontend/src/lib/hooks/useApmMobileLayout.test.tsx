import { act, cleanup, renderHook } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { useApmMobileLayout } from './useApmMobileLayout'

function resize(width: number): void {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: width })
    window.dispatchEvent(new Event('resize'))
}

describe('APM mobile layout', () => {
    let unmountFlags: () => void
    const originalWidth = window.innerWidth

    beforeEach(() => {
        initKeaTests()
        unmountFlags = featureFlagLogic.mount()
    })

    afterEach(() => {
        cleanup()
        unmountFlags()
        resize(originalWidth)
    })

    it.each([320, 390, 430, 768, 844, 991, 992, 1024, 1440])('limits the rollout at width %i', (width) => {
        resize(width)
        const { result } = renderHook(() => useApmMobileLayout())
        expect(result.current).toBe(false)
        act(() =>
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.APM_MOBILE_TRIAGE], {
                [FEATURE_FLAGS.APM_MOBILE_TRIAGE]: true,
            })
        )
        expect(result.current).toBe(width < 992)
        act(() => featureFlagLogic.actions.setFeatureFlags([], {}))
        expect(result.current).toBe(false)
    })

    it('responds to rotation without reloading', () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.APM_MOBILE_TRIAGE], {
            [FEATURE_FLAGS.APM_MOBILE_TRIAGE]: true,
        })
        resize(768)
        const { result } = renderHook(() => useApmMobileLayout())
        expect(result.current).toBe(true)
        act(() => resize(1024))
        expect(result.current).toBe(false)
        act(() => resize(768))
        expect(result.current).toBe(true)
    })
})
