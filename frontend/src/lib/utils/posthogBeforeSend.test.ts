import posthog, { BeforeSendFn, CaptureResult } from 'posthog-js'

import { registerBeforeSendFilter } from './posthogBeforeSend'

describe('registerBeforeSendFilter', () => {
    const setConfig = posthog.set_config as jest.Mock
    const cleanups: Array<() => void> = []

    const register = (filter: BeforeSendFn): void => {
        cleanups.push(registerBeforeSendFilter(filter))
    }

    // The registry always points posthog at the same composed function; grab it from set_config.
    const composed = (): BeforeSendFn => {
        const lastCall = setConfig.mock.calls[setConfig.mock.calls.length - 1]
        return lastCall[0].before_send
    }

    beforeEach(() => setConfig.mockClear())
    afterEach(() => {
        cleanups.splice(0).forEach((un) => un())
    })

    const event = (name: string): CaptureResult => ({ event: name }) as CaptureResult

    it('runs filters in registration order and short-circuits on the first null', () => {
        const dropFoo = jest.fn((e: CaptureResult | null) => (e?.event === 'foo' ? null : e))
        const tag = jest.fn((e: CaptureResult | null) => (e ? ({ ...e, tagged: true } as CaptureResult) : e))
        register(dropFoo)
        register(tag)

        const run = composed()
        expect(run(event('foo'))).toBeNull()
        expect(tag).not.toHaveBeenCalled()

        expect(run(event('bar'))).toEqual({ event: 'bar', tagged: true })
    })

    it('unregistering one filter leaves the others running', () => {
        const dropFoo = jest.fn((e: CaptureResult | null) => (e?.event === 'foo' ? null : e))
        const dropBar = jest.fn((e: CaptureResult | null) => (e?.event === 'bar' ? null : e))
        register(dropFoo)
        const unregisterBar = registerBeforeSendFilter(dropBar)

        unregisterBar()

        const run = composed()
        expect(run(event('foo'))).toBeNull()
        expect(run(event('bar'))).toEqual(event('bar'))
    })

    it('updates posthog config on both register and unregister', () => {
        const unregister = registerBeforeSendFilter((e) => e)
        expect(setConfig).toHaveBeenCalledWith(expect.objectContaining({ before_send: expect.any(Function) }))
        setConfig.mockClear()
        unregister()
        expect(setConfig).toHaveBeenCalledWith(expect.objectContaining({ before_send: expect.any(Function) }))
    })
})
