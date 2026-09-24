import { NinePServer } from './ninepServer'
import { TerminalWorkerClient } from './TerminalWorkerClient'

class TestWorker {
    static instance: TestWorker
    onmessage?: (event: MessageEvent) => void
    onerror?: (event: ErrorEvent) => void
    onmessageerror?: () => void
    postMessage = jest.fn()
    terminate = jest.fn()

    constructor() {
        TestWorker.instance = this
    }
}

describe('terminal worker connection', () => {
    const originalWorker = globalThis.Worker
    const boot = {
        wasmUrl: 'https://example.com/v86.wasm',
        bios: new ArrayBuffer(0),
        vgaBios: new ArrayBuffer(0),
        kernel: new ArrayBuffer(0),
        canvas: {} as OffscreenCanvas,
    }

    beforeEach(() => {
        globalThis.Worker = TestWorker as unknown as typeof Worker
        jest.useFakeTimers()
    })

    afterEach(() => {
        globalThis.Worker = originalWorker
        jest.useRealTimers()
    })

    it('matches concurrent filesystem replies and ignores late replies after stopping', async () => {
        const replies: ((bytes: Uint8Array) => void)[] = []
        const server = { handle: jest.fn((_bytes, reply) => replies.push(reply)) } as unknown as NinePServer
        const client = new TerminalWorkerClient(boot, server, jest.fn())
        const worker = TestWorker.instance
        worker.onmessage!({ data: { type: 'loaded' } } as MessageEvent)
        await client.loaded
        for (const id of [10, 20, 30]) {
            worker.onmessage!({ data: { type: '9p', id, bytes: new Uint8Array([id]) } } as MessageEvent)
        }
        const first = new Uint8Array([1])
        const second = new Uint8Array([2])
        replies[1](second)
        replies[0](first)
        expect(worker.postMessage.mock.calls.slice(1)).toEqual([
            [{ type: '9p', id: 20, bytes: second }, [second.buffer]],
            [{ type: '9p', id: 10, bytes: first }, [first.buffer]],
        ])
        client.dispose()
        replies[2](new Uint8Array([3]))
        worker.onmessage!({ data: { type: '9p', id: 40, bytes: new Uint8Array([4]) } } as MessageEvent)
        expect(worker.postMessage).toHaveBeenCalledTimes(3)
        expect(server.handle).toHaveBeenCalledTimes(3)
        expect(worker.terminate).toHaveBeenCalledTimes(1)
    })

    it.each(['error', 'messageerror', 'timeout', 'stop'])(
        'settles startup and terminates the worker on %s',
        async (reason) => {
            const onError = jest.fn()
            const client = new TerminalWorkerClient(boot, {} as NinePServer, onError)
            const worker = TestWorker.instance
            const rejected = await expect(client.loaded).rejects.toBeInstanceOf(Error)
            if (reason === 'error') {
                worker.onerror!(new ErrorEvent('error'))
            } else if (reason === 'messageerror') {
                worker.onmessageerror!()
            } else if (reason === 'timeout') {
                jest.runOnlyPendingTimers()
            } else {
                client.dispose()
            }
            await rejected
            client.dispose()
            expect(worker.terminate).toHaveBeenCalledTimes(1)
            expect(jest.getTimerCount()).toBe(0)
            expect(onError).toHaveBeenCalledTimes(reason === 'stop' ? 0 : 1)
        }
    )
})
