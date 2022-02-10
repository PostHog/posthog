import { PluginsServerConfig } from '../../src/types'
import { delay } from '../../src/utils/utils'
import { PromiseManager } from './../../src/worker/vm/promise-manager'

jest.setTimeout(10000)

describe('PromiseManager', () => {
    let promiseManager: PromiseManager

    beforeEach(() => {
        promiseManager = new PromiseManager({ MAX_PENDING_PROMISES_PER_WORKER: 1 } as PluginsServerConfig)
    })

    test('promise manager awaits promises if above limit', async () => {
        const hello = jest.fn()
        const promise = async () => {
            await delay(5000)
            hello()
        }
        await promiseManager.trackPromise(promise())
        console.log('woop', promiseManager.pendingPromises)
        expect(promiseManager.pendingPromises.size).toEqual(1)
        expect(hello).not.toHaveBeenCalled()

        await promiseManager.trackPromise(promise())
        expect(promiseManager.pendingPromises.size).toEqual(1)
        expect(hello).toHaveBeenCalled()
    })
})
