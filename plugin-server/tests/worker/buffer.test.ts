import { delay } from '../../src/utils/utils'
import { PromiseManager } from '../../src/worker/vm/promise-manager'
import { Hub } from './../../src/types'
import { ExportEventsBuffer } from './../../src/worker/vm/upgrades/utils/export-events-buffer'

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

describe('ExportEventsBuffer', () => {
    let promiseManager: PromiseManager
    let mockHub: Hub
    let exportEventsBuffer: ExportEventsBuffer

    beforeEach(() => {
        promiseManager = new PromiseManager({ MAX_PENDING_PROMISES_PER_WORKER: 1 } as any)
        mockHub = { promiseManager } as any
        exportEventsBuffer = new ExportEventsBuffer(mockHub, { limit: 2 })
    })

    test('add and flush work as expected', async () => {
        jest.spyOn(promiseManager, 'trackPromise')
        jest.spyOn(exportEventsBuffer, 'flush')

        exportEventsBuffer._flush = jest.fn(async () => {
            await delay(3000)
        })

        await exportEventsBuffer.add({ event: 'event1' }, 1)
        expect(exportEventsBuffer.points).toEqual(1)
        expect(exportEventsBuffer.buffer.length).toEqual(1)
        expect(exportEventsBuffer.flush).not.toHaveBeenCalled()

        await exportEventsBuffer.add({ event: 'event2' }, 1)
        expect(exportEventsBuffer.points).toEqual(2)
        expect(exportEventsBuffer.buffer.length).toEqual(2)
        expect(exportEventsBuffer.flush).not.toHaveBeenCalled()

        await exportEventsBuffer.add({ event: 'event3' }, 1)
        expect(exportEventsBuffer.points).toEqual(1)
        expect(exportEventsBuffer.buffer.length).toEqual(1)
        expect(exportEventsBuffer.buffer).toEqual([{ event: 'event3' }])
        expect(exportEventsBuffer._flush).toHaveBeenCalledWith(
            [{ event: 'event1' }, { event: 'event2' }],
            2,
            expect.any(Date)
        )
    })

    test('flush works correctly with promise manager', async () => {
        jest.spyOn(promiseManager, 'trackPromise')
        jest.spyOn(exportEventsBuffer, 'flush')

        exportEventsBuffer._flush = jest.fn(async () => {
            await delay(3000)
        })

        // add a promise
        promiseManager.trackPromise(delay(3000))
        expect(promiseManager.pendingPromises.size).toEqual(1)

        await exportEventsBuffer.add({ event: 'event1' }, 1)
        expect(exportEventsBuffer.points).toEqual(1)
        expect(exportEventsBuffer.buffer.length).toEqual(1)
        expect(exportEventsBuffer.flush).not.toHaveBeenCalled()
        expect(promiseManager.trackPromise).toHaveBeenCalledTimes(1)
        expect(promiseManager.pendingPromises.size).toEqual(1)

        await exportEventsBuffer.add({ event: 'event2' }, 2)
        expect(exportEventsBuffer.flush).toHaveBeenCalled()
        expect(promiseManager.trackPromise).toHaveBeenCalledTimes(2)
        expect(promiseManager.pendingPromises.size).toEqual(1)
    })
})
