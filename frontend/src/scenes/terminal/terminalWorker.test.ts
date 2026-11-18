import type { V86, V86Options } from 'v86'

import type { TerminalWorkerRequest } from './terminalWorkerProtocol'

jest.mock('v86', () => ({
    V86: jest.fn<Pick<V86, 'add_listener'>, [V86Options]>(() => ({ add_listener: jest.fn() })),
}))

describe('terminal VM worker', () => {
    const originalOnMessage = self.onmessage

    afterEach(() => {
        self.onmessage = originalOnMessage
        jest.restoreAllMocks()
    })

    it('copies guest memory and drops flushed replies without confusing reused tags', () => {
        const send = jest.spyOn(globalThis, 'postMessage').mockImplementation(() => {})
        jest.spyOn(self, 'addEventListener').mockImplementation(() => {})
        let handle: NonNullable<V86Options['filesystem']>['handle9p']
        const receive = (data: TerminalWorkerRequest): void => self.onmessage!(new MessageEvent('message', { data }))
        jest.isolateModules(() => {
            const { V86 } = jest.requireMock<typeof import('v86')>('v86')
            require('./terminalWorker')
            receive({
                type: 'start',
                wasmUrl: 'https://example.com/v86.wasm',
                bios: new ArrayBuffer(0),
                vgaBios: new ArrayBuffer(0),
                kernel: new ArrayBuffer(0),
                canvas: { getContext: () => ({}) } as unknown as OffscreenCanvas,
            })
            handle = jest.mocked(V86).mock.calls[0][0].filesystem!.handle9p!
        })
        const canceled = jest.fn()
        const flush = jest.fn()
        const replacement = jest.fn()
        const request = new Uint8Array([7, 0, 0, 0, 116, 42, 0])
        handle!(request, canceled)
        request[4] = 0
        expect(send.mock.calls[0][0]).toMatchObject({
            type: '9p',
            id: 0,
            bytes: new Uint8Array([7, 0, 0, 0, 116, 42, 0]),
        })
        handle!(new Uint8Array([9, 0, 0, 0, 108, 43, 0, 42, 0]), flush)
        handle!(new Uint8Array([7, 0, 0, 0, 116, 42, 0]), replacement)
        const bytes = new Uint8Array([1])
        receive({ type: '9p', id: 0, bytes })
        receive({ type: '9p', id: 2, bytes })
        receive({ type: '9p', id: 1, bytes })
        expect(canceled).not.toHaveBeenCalled()
        expect(replacement).toHaveBeenCalledWith(bytes)
        expect(flush).toHaveBeenCalledWith(bytes)
    })
})
