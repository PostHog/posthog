import { CanvasDocumentBridge } from './canvasDocumentBridge'

describe('CanvasDocumentBridge', () => {
    const ports: { postMessage: jest.Mock; close: jest.Mock; onmessage: unknown }[] = []

    beforeEach(() => {
        ports.length = 0
        ;(globalThis as any).MessageChannel = jest.fn(() => {
            const pair = [0, 1].map(() => ({ postMessage: jest.fn(), close: jest.fn(), onmessage: null }))
            ports.push(pair[0])
            return { port1: pair[0], port2: pair[1] }
        })
    })

    test.each([
        { sender: 'the framed wrapper', fromFrame: true, stillConnected: false },
        { sender: 'another window', fromFrame: false, stillConnected: true },
    ])('a navigated message from $sender keeps the port open: $stillConnected', ({ fromFrame, stillConnected }) => {
        const iframe = document.createElement('iframe')
        document.body.append(iframe)
        const bridge = new CanvasDocumentBridge(iframe, jest.fn(), jest.fn())
        iframe.dispatchEvent(new Event('load'))

        window.dispatchEvent(
            new MessageEvent('message', {
                data: { channel: 'posthog-canvas', type: 'navigated' },
                source: fromFrame ? iframe.contentWindow : window,
            })
        )
        bridge.post({ channel: 'posthog-canvas', type: 'set-theme', theme: 'dark' })

        expect(ports[0].postMessage).toHaveBeenCalledTimes(stillConnected ? 1 : 0)
        bridge.close()
        iframe.remove()
    })
})
