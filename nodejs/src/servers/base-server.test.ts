import http from 'http'

import { getDefaultConfig } from '~/common/config/config'

import { ServerLifecycle } from './base-server'

describe('ServerLifecycle', () => {
    let lifecycle: ServerLifecycle
    let port: number
    let releaseResponse: () => void
    let requestReceived: Promise<void>

    beforeEach(async () => {
        lifecycle = new ServerLifecycle(
            { ...getDefaultConfig(), HTTP_SERVER_DRAIN_TIMEOUT_MS: 60_000 },
            { internalApiAuthExcludedPathPrefixes: ['/big'] }
        )
        let onRequest: () => void
        requestReceived = new Promise((resolve) => (onRequest = resolve))
        const released = new Promise<void>((resolve) => (releaseResponse = resolve))
        lifecycle.expressApp.get('/big', async (_req, res) => {
            onRequest()
            await released
            res.send(Buffer.alloc(50 * 1024 * 1024))
        })
        await new Promise<void>((resolve) => {
            lifecycle.httpServer = lifecycle.expressApp.listen(0, () => resolve()) as any
        })
        port = (lifecycle.expressApp as any).address().port
    })

    afterEach(() => {
        releaseResponse()
        ;(lifecycle.httpServer as any)?.close()
    })

    it('waits until a sent response has fully reached a slow client', async () => {
        let receivedBytes = 0
        let pausedResponse: http.IncomingMessage | undefined
        const responseEnded = new Promise<void>((resolve) => {
            http.get({ port, path: '/big', agent: false, headers: { connection: 'close' } }, (res) => {
                pausedResponse = res.pause()
                res.on('data', (chunk) => (receivedBytes += chunk.length))
                res.on('end', resolve)
            })
        })
        await requestReceived
        releaseResponse()

        jest.useFakeTimers({ doNotFake: ['nextTick', 'setImmediate', 'queueMicrotask'] })
        try {
            let drained = false
            void lifecycle.drainConnections().then(() => (drained = true))
            await jest.advanceTimersByTimeAsync(10_000)
            expect(drained).toBe(false)

            pausedResponse!.resume()
            await responseEnded
            expect(receivedBytes).toEqual(50 * 1024 * 1024)
            await jest.advanceTimersByTimeAsync(200)
            expect(drained).toBe(true)
        } finally {
            jest.useRealTimers()
        }
    })

    it('does not wait for a request the client aborted', async () => {
        const req = http.get({ port, path: '/big', agent: false }).on('error', () => {})
        await requestReceived
        req.destroy()

        await expect(lifecycle.drainConnections()).resolves.toBeUndefined()
    })
})
