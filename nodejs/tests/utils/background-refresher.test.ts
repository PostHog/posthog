import { BackgroundRefresher } from '../../src/utils/background-refresher'

const realNow = Date.now

describe('getNextRetryMs', () => {
    jest.useFakeTimers()
    jest.setTimeout(1000)
    let refreshFunction = jest.fn()
    let refresher = new BackgroundRefresher(refreshFunction)

    beforeEach(() => {
        refreshFunction = jest.fn()
        refresher = new BackgroundRefresher(refreshFunction, 100)
    })

    beforeAll(() => {
        global.Date.now = jest.fn(() => new Date('2019-04-07T10:20:30Z').getTime())
    })

    afterAll(() => {
        global.Date.now = realNow
    })

    it('simple gets', async () => {
        refreshFunction.mockResolvedValue('foo')
        await expect(refresher.get()).resolves.toEqual('foo')
        refreshFunction.mockResolvedValue('foo2')
        await expect(refresher.get()).resolves.toEqual('foo')
        await expect(refresher.refresh()).resolves.toEqual('foo2')
        await expect(refresher.get()).resolves.toEqual('foo2')
    })

    it('only one call per refresh', async () => {
        refreshFunction.mockImplementation(async () => {
            await new Promise((resolve) => setTimeout(resolve, 100))
            return 'foo'
        })

        const promises: Promise<any>[] = []

        expect(refreshFunction).toHaveBeenCalledTimes(0)
        promises.push(refresher.get())
        expect(refreshFunction).toHaveBeenCalledTimes(1)
        promises.push(refresher.get())
        promises.push(refresher.get())
        expect(refreshFunction).toHaveBeenCalledTimes(1)
        jest.runOnlyPendingTimers()

        expect(await Promise.all(promises)).toEqual(['foo', 'foo', 'foo'])
    })

    it('refreshes in the background', async () => {
        let count = 1
        let timeAdavance = 0
        global.Date.now = jest.fn(() => realNow() + timeAdavance)
        refresher = new BackgroundRefresher(refreshFunction, 10000)

        refreshFunction.mockImplementation(async () => {
            await new Promise((r) => setTimeout(r, 1000))
            return 'foo' + count++
        })

        // First time we need to trigger the timer before awaiting as it waits for the value
        let response = refresher.get()
        jest.runOnlyPendingTimers()
        await expect(response).resolves.toEqual('foo1')
        await expect(refresher.get()).resolves.toEqual('foo1')
        expect(refreshFunction).toHaveBeenCalledTimes(1)
        // Advance time forward by more than the refresh interval
        timeAdavance = 10000 + 1000
        // This will trigger the background refresh
        response = refresher.get()
        // which we resolve the timeout for
        jest.runOnlyPendingTimers()
        // the original call gets the old value as it doesn't wait
        await expect(response).resolves.toEqual('foo1')
        expect(refreshFunction).toHaveBeenCalledTimes(2)
        // the next call gets the new value
        await expect(refresher.get()).resolves.toEqual('foo2')
        expect(refreshFunction).toHaveBeenCalledTimes(2)
    })
})
