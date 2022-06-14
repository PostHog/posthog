import { ProcessedPluginEvent, RetryError } from '@posthog/plugin-scaffold'

import { Hub } from '../../src/types'
import { delay,UUID } from '../../src/utils/utils'
import { runRetriableFunction } from '../../src/worker/plugins/run'
import { pluginConfig39 } from '../helpers/plugins'

jest.mock('../../src/utils/utils', () => ({
    ...jest.requireActual('../../src/utils/utils'),
    delay: jest.fn(), // We don't want retries to actually use exponential backoff in tests
}))
jest.mock('../../src/utils/db/error')

const mockHub: Hub = {
    instanceId: new UUID('F8B2F832-6639-4596-ABFC-F9664BC88E84'),
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

describe('runRetriableFunction', () => {
    it('run the function once if it resolves', async () => {
        const tryFn = jest.fn().mockResolvedValue('Guten Abend')
        const catchFn = jest.fn()
        const finallyFn = jest.fn()

        const promise = runRetriableFunction(mockHub, pluginConfig39, testEvent, 'on_foo', tryFn, catchFn, finallyFn)

        await expect(promise).resolves.toEqual(1)
        expect(tryFn).toHaveBeenCalledTimes(1)
        expect(catchFn).toHaveBeenCalledTimes(0)
        expect(finallyFn).toHaveBeenCalledTimes(1)
        expect(delay).not.toHaveBeenCalled()
    })

    it('catches non-RetryError error', async () => {
        const tryFn = jest.fn().mockImplementation(() => {
            // Faulty plugin code might look like this
            let bar
            bar.baz = 123
        })
        const catchFn = jest.fn()
        const finallyFn = jest.fn()

        const promise = runRetriableFunction(mockHub, pluginConfig39, testEvent, 'on_foo', tryFn, catchFn, finallyFn)

        await expect(promise).resolves.toEqual(1)
        expect(tryFn).toHaveBeenCalledTimes(1)
        expect(catchFn).toHaveBeenCalledTimes(1)
        expect(catchFn).toHaveBeenCalledWith(expect.any(TypeError))
        expect(finallyFn).toHaveBeenCalledTimes(1)
        expect(delay).not.toHaveBeenCalled()
    })

    it('catches RetryError error and retries up to 5 times', async () => {
        const tryFn = jest.fn().mockImplementation(() => {
            throw new RetryError()
        })
        const catchFn = jest.fn()
        const finallyFn = jest.fn()

        const promise = runRetriableFunction(mockHub, pluginConfig39, testEvent, 'on_foo', tryFn, catchFn, finallyFn)

        await expect(promise).resolves.toEqual(5)
        expect(tryFn).toHaveBeenCalledTimes(5)
        expect(catchFn).toHaveBeenCalledTimes(1)
        expect(catchFn).toHaveBeenCalledWith(expect.any(RetryError))
        expect(finallyFn).toHaveBeenCalledTimes(1)
        expect(delay).toHaveBeenCalledTimes(4)
        expect(delay).toHaveBeenNthCalledWith(1, 5_000)
        expect(delay).toHaveBeenNthCalledWith(2, 10_000)
        expect(delay).toHaveBeenNthCalledWith(3, 20_000)
        expect(delay).toHaveBeenNthCalledWith(4, 40_000)
    })

    it('catches RetryError error and retries up to 5 times', async () => {
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

        const promise = runRetriableFunction(mockHub, pluginConfig39, testEvent, 'on_foo', tryFn, catchFn, finallyFn)

        await expect(promise).resolves.toEqual(3)
        expect(tryFn).toHaveBeenCalledTimes(3)
        expect(catchFn).toHaveBeenCalledTimes(0)
        expect(finallyFn).toHaveBeenCalledTimes(1)
        expect(delay).toHaveBeenCalledTimes(2)
        expect(delay).toHaveBeenNthCalledWith(1, 5_000)
        expect(delay).toHaveBeenNthCalledWith(2, 10_000)
    })
})
