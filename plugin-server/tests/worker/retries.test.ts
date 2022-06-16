import { ProcessedPluginEvent, RetryError } from '@posthog/plugin-scaffold'

import { Hub } from '../../src/types'
import { UUID } from '../../src/utils/utils'
import { getNextRetryMs, runRetriableFunction } from '../../src/worker/retries'
import { PromiseManager } from '../../src/worker/vm/promise-manager'
import { pluginConfig39 } from '../helpers/plugins'

jest.useFakeTimers()
jest.spyOn(global, 'setTimeout')
jest.mock('../../src/utils/db/error') // Mocking setError which we don't need in tests

const mockHub: Hub = {
    instanceId: new UUID('F8B2F832-6639-4596-ABFC-F9664BC88E84'),
    promiseManager: new PromiseManager({ MAX_PENDING_PROMISES_PER_WORKER: 1 } as any),
} as Hub

const testEvent: ProcessedPluginEvent = {
    uuid: '4CCCB5FD-BD27-4D6C-8737-88EB7294C437',
    distinct_id: 'my_id',
    ip: '127.0.0.1',
    team_id: 3,
    timestamp: '2023-04-01T00:00:00.000Z',
    event: 'default event',
    properties: {},
}

describe('getNextRetryMs', () => {
    it('returns the correct number of milliseconds with a multiplier of 1', () => {
        expect(getNextRetryMs(500, 1, 1)).toBe(500)
        expect(getNextRetryMs(500, 1, 2)).toBe(500)
        expect(getNextRetryMs(500, 1, 3)).toBe(500)
        expect(getNextRetryMs(500, 1, 4)).toBe(500)
        expect(getNextRetryMs(500, 1, 5)).toBe(500)
    })

    it('returns the correct number of milliseconds with a multiplier of 2', () => {
        expect(getNextRetryMs(4000, 2, 1)).toBe(4000)
        expect(getNextRetryMs(4000, 2, 2)).toBe(8000)
        expect(getNextRetryMs(4000, 2, 3)).toBe(16000)
        expect(getNextRetryMs(4000, 2, 4)).toBe(32000)
        expect(getNextRetryMs(4000, 2, 5)).toBe(64000)
    })

    it('throws on attempt below 0', () => {
        expect(() => getNextRetryMs(4000, 2, 0)).toThrowError('Attempts are indexed starting with 1')
        expect(() => getNextRetryMs(4000, 2, -1)).toThrowError('Attempts are indexed starting with 1')
    })
})

describe('runRetriableFunction', () => {
    it('runs the function once if it resolves on first try', async () => {
        const tryFn = jest.fn().mockResolvedValue('Guten Abend')
        const catchFn = jest.fn()
        const finallyFn = jest.fn()

        const promise = new Promise<number>((resolve) => {
            finallyFn.mockImplementation((attempt: number) => resolve(attempt))
            void runRetriableFunction('on_foo', mockHub, pluginConfig39, {
                event: testEvent,
                tryFn,
                catchFn,
                finallyFn,
            })
        })
        jest.runAllTimers()

        await expect(promise).resolves.toEqual(1)
        expect(tryFn).toHaveBeenCalledTimes(1)
        expect(catchFn).toHaveBeenCalledTimes(0)
        expect(finallyFn).toHaveBeenCalledTimes(1)
        expect(setTimeout).not.toHaveBeenCalled()
    })

    it('catches non-RetryError error', async () => {
        const tryFn = jest.fn().mockImplementation(() => {
            // Faulty plugin code might look like this
            let bar
            bar.baz = 123
        })
        const catchFn = jest.fn()
        const finallyFn = jest.fn()

        const promise = new Promise<number>((resolve) => {
            finallyFn.mockImplementation((attempt: number) => resolve(attempt))
            void runRetriableFunction('on_foo', mockHub, pluginConfig39, {
                event: testEvent,
                tryFn,
                catchFn,
                finallyFn,
            })
        })
        jest.runAllTimers()

        await expect(promise).resolves.toEqual(1)
        expect(tryFn).toHaveBeenCalledTimes(1)
        expect(catchFn).toHaveBeenCalledTimes(1)
        expect(catchFn).toHaveBeenCalledWith(expect.any(TypeError))
        expect(finallyFn).toHaveBeenCalledTimes(1)
        expect(setTimeout).not.toHaveBeenCalled()
    })

    it('catches RetryError error and retries up to 5 times', async () => {
        const tryFn = jest.fn().mockImplementation(() => {
            throw new RetryError()
        })
        const catchFn = jest.fn()
        const finallyFn = jest.fn()

        const promise = new Promise<number>((resolve) => {
            finallyFn.mockImplementation((attempt: number) => resolve(attempt))
            void runRetriableFunction('on_foo', mockHub, pluginConfig39, {
                event: testEvent,
                tryFn,
                catchFn,
                finallyFn,
            })
        })

        expect(tryFn).toHaveBeenCalledTimes(1)
        expect(finallyFn).toHaveBeenCalledTimes(0)
        expect(setTimeout).toHaveBeenCalledTimes(1)

        jest.runAllTimers()

        await expect(promise).resolves.toEqual(5)
        expect(tryFn).toHaveBeenCalledTimes(5)
        expect(catchFn).toHaveBeenCalledTimes(1)
        expect(catchFn).toHaveBeenCalledWith(expect.any(RetryError))
        expect(finallyFn).toHaveBeenCalledTimes(1)
        expect(setTimeout).toHaveBeenCalledTimes(4)
        expect(setTimeout).toHaveBeenNthCalledWith(1, expect.any(Function), 5_000)
        expect(setTimeout).toHaveBeenNthCalledWith(2, expect.any(Function), 10_000)
        expect(setTimeout).toHaveBeenNthCalledWith(3, expect.any(Function), 20_000)
        expect(setTimeout).toHaveBeenNthCalledWith(4, expect.any(Function), 40_000)
    })

    it('catches RetryError error and allow the function to succeed on 3rd attempt', async () => {
        const tryFn = jest
            .fn()
            .mockImplementationOnce(() => {
                throw new RetryError()
            })
            .mockImplementationOnce(() => {
                throw new RetryError()
            })
            .mockResolvedValue('Gute Nacht')
        const catchFn = jest.fn()
        const finallyFn = jest.fn()

        const promise = new Promise<number>((resolve) => {
            finallyFn.mockImplementation((attempt: number) => resolve(attempt))
            void runRetriableFunction('on_foo', mockHub, pluginConfig39, {
                event: testEvent,
                tryFn,
                catchFn,
                finallyFn,
            })
        })

        expect(tryFn).toHaveBeenCalledTimes(1)
        expect(finallyFn).toHaveBeenCalledTimes(0)
        expect(setTimeout).toHaveBeenCalledTimes(1)

        jest.runAllTimers()

        await expect(promise).resolves.toEqual(3)
        expect(tryFn).toHaveBeenCalledTimes(3)
        expect(catchFn).toHaveBeenCalledTimes(0)
        expect(finallyFn).toHaveBeenCalledTimes(1)
        expect(setTimeout).toHaveBeenCalledTimes(2)
        expect(setTimeout).toHaveBeenNthCalledWith(1, expect.any(Function), 5_000)
        expect(setTimeout).toHaveBeenNthCalledWith(2, expect.any(Function), 10_000)
    })
})
