import { BuiltLogic, Logic } from 'kea'

import { sceneLogic } from 'scenes/sceneLogic'

import { tabAwareUrlToAction } from './tabAwareUrlToAction'

let capturedPayload: Record<string, (...args: any[]) => any> | undefined

jest.mock('kea-router', () => ({
    urlToAction: (payload: Record<string, (...args: any[]) => any>) => {
        capturedPayload = payload
        return () => undefined
    },
}))

jest.mock('scenes/sceneLogic', () => ({
    sceneLogic: {
        isMounted: jest.fn(),
        values: { activeTabId: undefined as string | undefined },
    },
}))

describe('tabAwareUrlToAction', () => {
    beforeEach(() => {
        capturedPayload = undefined
        ;(sceneLogic.isMounted as jest.Mock).mockReset()
        ;(sceneLogic as any).values.activeTabId = 'tab-1'
    })

    const buildWrapper = (logic: BuiltLogic<Logic>, handler: jest.Mock): void => {
        tabAwareUrlToAction(() => ({
            '/some-url': handler,
        }))(logic)
    }

    it('does not invoke the inner handler when the per-tab logic is unmounted', () => {
        ;(sceneLogic.isMounted as jest.Mock).mockReturnValue(true)
        const innerHandler = jest.fn()
        const logic = {
            isMounted: () => false,
            props: { tabId: 'tab-1' },
        } as unknown as BuiltLogic<Logic>

        buildWrapper(logic, innerHandler)

        expect(capturedPayload).not.toBeUndefined()
        const wrapped = capturedPayload!['/some-url']
        // Simulating kea-router's popListener firing after the logic has unmounted
        // (the production crash was "X.create is not a function" inside the inner
        // handler dispatching kea actions on the unmounted logic).
        expect(() => wrapped({}, {}, {}, undefined, undefined)).not.toThrow()
        expect(innerHandler).not.toHaveBeenCalled()
    })

    it('invokes the inner handler when the logic is mounted and the tab is active', () => {
        ;(sceneLogic.isMounted as jest.Mock).mockReturnValue(true)
        ;(sceneLogic as any).values.activeTabId = 'tab-1'
        const innerHandler = jest.fn().mockReturnValue('ok')
        const logic = {
            isMounted: () => true,
            props: { tabId: 'tab-1' },
        } as unknown as BuiltLogic<Logic>

        buildWrapper(logic, innerHandler)
        const wrapped = capturedPayload!['/some-url']
        const result = wrapped({}, {}, {}, undefined, undefined)

        expect(innerHandler).toHaveBeenCalledTimes(1)
        expect(result).toBe('ok')
    })

    it('skips the inner handler when the per-tab logic is mounted but the tab is inactive', () => {
        ;(sceneLogic.isMounted as jest.Mock).mockReturnValue(true)
        ;(sceneLogic as any).values.activeTabId = 'tab-other'
        const innerHandler = jest.fn()
        const logic = {
            isMounted: () => true,
            props: { tabId: 'tab-1' },
        } as unknown as BuiltLogic<Logic>

        buildWrapper(logic, innerHandler)
        const wrapped = capturedPayload!['/some-url']
        wrapped({}, {}, {}, undefined, undefined)

        expect(innerHandler).not.toHaveBeenCalled()
    })

    it('falls back to invoking the inner handler when sceneLogic is not mounted but logic is', () => {
        ;(sceneLogic.isMounted as jest.Mock).mockReturnValue(false)
        const innerHandler = jest.fn().mockReturnValue('ok')
        const logic = {
            isMounted: () => true,
            props: { tabId: 'tab-1' },
        } as unknown as BuiltLogic<Logic>

        buildWrapper(logic, innerHandler)
        const wrapped = capturedPayload!['/some-url']
        const result = wrapped({}, {}, {}, undefined, undefined)

        expect(innerHandler).toHaveBeenCalledTimes(1)
        expect(result).toBe('ok')
    })
})
