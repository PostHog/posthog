import { delay } from '../../src/utils/utils'
import { PromiseManager } from '../../src/worker/vm/promise-manager'

jest.setTimeout(100000)

describe('PromiseManager', () => {
    let promiseManager: PromiseManager

    beforeEach(() => {
        promiseManager = new PromiseManager({ MAX_PENDING_PROMISES_PER_WORKER: 1 } as any)
    })

    afterEach(async () => {
        await Promise.all(promiseManager.pendingPromises)
    })

    test('promise manager awaits promises if above limit', async () => {
        const hello = jest.fn()
        const promise = async () => {
            await delay(3000)
            hello()
        }

        // we track the promise but don't await it
        promiseManager.trackPromise(promise())
        expect(promiseManager.pendingPromises.size).toEqual(1)
        expect(hello).not.toHaveBeenCalled()

        // we add another promise above the limit
        promiseManager.trackPromise(promise())
        expect(promiseManager.pendingPromises.size).toEqual(2)
        expect(hello).not.toHaveBeenCalled()

        // we chop one promise off by awaiting it
        await promiseManager.awaitPromisesIfNeeded()
        expect(hello).toHaveBeenCalled()
        expect(promiseManager.pendingPromises.size).toEqual(1)
    })
})
