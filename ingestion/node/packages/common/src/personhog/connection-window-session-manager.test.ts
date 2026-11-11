import { ConnectionWindowSessionManager } from './connection-window-session-manager'

function makeSession(): { setLocalWindowSize: jest.Mock } {
    return { setLocalWindowSize: jest.fn() }
}

function makeInner(streams: { session: unknown }[]): {
    authority: string
    request: jest.Mock
    notifyResponseByteRead: jest.Mock
} {
    const request = jest.fn()
    for (const stream of streams) {
        request.mockResolvedValueOnce(stream)
    }
    return { authority: 'localhost:1', request, notifyResponseByteRead: jest.fn() }
}

describe('ConnectionWindowSessionManager', () => {
    it('widens each session once, however many streams it carries', async () => {
        const first = makeSession()
        const second = makeSession()
        const inner = makeInner([{ session: first }, { session: first }, { session: second }])
        const manager = new ConnectionWindowSessionManager(inner as any, 8 * 1024 * 1024)

        for (let i = 0; i < 3; i++) {
            await manager.request('POST', '/svc/Method', {}, {})
        }

        expect(first.setLocalWindowSize).toHaveBeenCalledTimes(1)
        expect(first.setLocalWindowSize).toHaveBeenCalledWith(8 * 1024 * 1024)
        expect(second.setLocalWindowSize).toHaveBeenCalledTimes(1)
    })

    it('passes through a stream that has already lost its session', async () => {
        const stream = { session: undefined }
        const inner = makeInner([stream])
        const manager = new ConnectionWindowSessionManager(inner as any, 1024)

        await expect(manager.request('POST', '/svc/Method', {}, {})).resolves.toBe(stream)
    })
})
