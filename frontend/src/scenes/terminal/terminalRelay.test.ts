import { FrameDecoder, TerminalNetplay, encodeFrame } from './terminalNetplay'

class FakeSocket extends EventTarget {
    static OPEN = 1
    static created: FakeSocket[] = []
    readyState = 0
    bufferedAmount = 0
    binaryType = 'blob'
    onopen: (() => void) | null = null
    onmessage: ((event: { data: string | ArrayBuffer }) => void) | null = null
    onclose: ((event: { code: number }) => void) | null = null
    onerror: (() => void) | null = null
    send = jest.fn()
    close = jest.fn()

    constructor(readonly url: string) {
        super()
        FakeSocket.created.push(this)
    }

    open(): void {
        this.readyState = 1
        this.onopen?.()
    }
}

describe('terminal game relay', () => {
    const originalSocket = globalThis.WebSocket
    const config = { url: 'wss://relay.example.com/netplay', token: 'test-only-access-token' }
    let session: AbortController
    let netplay: TerminalNetplay
    let frames: Uint8Array[]
    const fromGuest = (peer: number, message: string | number[]): void => {
        const payload = typeof message === 'string' ? new TextEncoder().encode(message) : Uint8Array.from(message)
        encodeFrame(peer, payload).forEach((byte) => netplay.receive(byte))
    }
    const messages = (): string[] =>
        frames.filter((frame) => frame[0] === 255).map((frame) => new TextDecoder().decode(frame.slice(1)))

    beforeEach(() => {
        jest.useFakeTimers()
        FakeSocket.created = []
        globalThis.WebSocket = FakeSocket as unknown as typeof WebSocket
        session = new AbortController()
        netplay = new TerminalNetplay('42', session.signal)
        frames = []
        const decoder = new FrameDecoder()
        netplay.attach((bytes) =>
            bytes.forEach((byte) => {
                const frame = decoder.push(byte)
                if (frame) {
                    frames.push(frame)
                }
            })
        )
        netplay.command(['configure', '--json', JSON.stringify(config)])
    })

    afterEach(() => {
        session.abort()
        globalThis.WebSocket = originalSocket
        jest.useRealTimers()
    })

    it.each(['host', 'join ABC123'])('carries %s and SLIP packets over the configured relay', (control) => {
        fromGuest(255, control)
        const socket = FakeSocket.created[0]
        expect(socket.url).toBe(config.url)
        socket.open()
        expect(JSON.parse(socket.send.mock.calls[0][0])).toEqual({
            action: control === 'host' ? 'host' : 'join',
            token: config.token,
            ...(control === 'host' ? {} : { room: 'ABC123' }),
        })
        socket.onmessage?.({ data: JSON.stringify({ type: control === 'host' ? 'room' : 'joined', room: 'ABC123' }) })
        expect(messages()).toEqual([control === 'host' ? 'room ABC123' : 'joined'])
        const peer = control === 'host' ? 1 : 0
        fromGuest(peer, [192, 219, 7])
        expect(socket.send).toHaveBeenLastCalledWith(Uint8Array.from([peer, 192, 219, 7]))
        socket.onmessage?.({ data: Uint8Array.from([peer, 192, 219, 8]).buffer })
        expect(frames.at(-1)).toEqual(Uint8Array.from([peer, 192, 219, 8]))
        fromGuest(255, 'launched')
        expect(socket.send.mock.calls.some(([value]) => value === 'launched')).toBe(control === 'host')
        netplay.command(['clear'])
        expect(socket.close).not.toHaveBeenCalled()
        session.abort()
        expect(socket.close).toHaveBeenCalledTimes(1)
        expect(socket.onmessage).toBeNull()
    })

    it.each(['timeout', 'error', 'rejected', 'malformed'])(
        'reports relay %s without exposing credentials',
        (failure) => {
            fromGuest(255, 'join ABC123')
            const socket = FakeSocket.created[0]
            if (failure === 'timeout') {
                jest.advanceTimersByTime(10_000)
            } else if (failure === 'error') {
                socket.onerror?.()
            } else if (failure === 'rejected') {
                socket.onclose?.({ code: 1008 })
            } else {
                socket.onmessage?.({ data: config.token })
            }
            expect(messages()).toHaveLength(1)
            expect(messages()[0]).toMatch(/^error /)
            expect(messages()[0]).not.toContain(config.token)
            expect(socket.close).toHaveBeenCalledTimes(1)
        }
    )

    it.each([
        'https://relay.example.com/netplay',
        'ws://relay.example.com/netplay',
        'wss://relay.example.com/netplay?token=secret',
        'wss://user:secret@relay.example.com/netplay',
    ])('rejects unsafe relay URL %s without replacing valid settings', (url) => {
        expect(() => netplay.command(['configure', '--json', JSON.stringify({ ...config, url })])).toThrow(
            'Invalid relay configuration'
        )
        fromGuest(255, 'host')
        expect(FakeSocket.created[0].url).toBe(config.url)
    })

    it('closes the previous game and bounds queued bytes on a slow connection', () => {
        fromGuest(255, 'host')
        const first = FakeSocket.created[0]
        first.open()
        first.bufferedAmount = 65536
        fromGuest(1, [1])
        expect(first.send).toHaveBeenCalledTimes(1)
        fromGuest(255, 'join ABC123')
        expect(first.close).toHaveBeenCalledTimes(1)
        session.abort()
        expect(FakeSocket.created[1].close).toHaveBeenCalledTimes(1)
        expect(() => netplay.command(['status'])).toThrow('The terminal stopped')
        expect(new TerminalNetplay('42', new AbortController().signal).command(['status'])).toContain('No game relay')
    })
})
