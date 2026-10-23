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
            { internalApiAuthExcludedPathPrefixes: ['/slow'] }
        )
        let onRequest: () => void
        requestReceived = new Promise((resolve) => (onRequest = resolve))
        const released = new Promise<void>((resolve) => (releaseResponse = resolve))
        lifecycle.expressApp.get('/slow', async (_req, res) => {
            onRequest()
            await released
            res.send('done')
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

    it('waits for an in-flight request to finish before draining completes', async () => {
        const response = new Promise<string>((resolve) => {
            http.get(`http://localhost:${port}/slow`, (res) => {
                let body = ''
                res.on('data', (chunk) => (body += chunk))
                res.on('end', () => resolve(body))
            })
        })
        await requestReceived

        jest.useFakeTimers({ doNotFake: ['nextTick', 'setImmediate', 'queueMicrotask'] })
        try {
            let drained = false
            void lifecycle.drainInFlightRequests().then(() => (drained = true))
            await jest.advanceTimersByTimeAsync(10_000)
            expect(drained).toBe(false)

            releaseResponse()
            expect(await response).toEqual('done')
            await jest.advanceTimersByTimeAsync(200)
            expect(drained).toBe(true)
        } finally {
            jest.useRealTimers()
        }
    })

    it('does not wait for a request the client aborted', async () => {
        const req = http.get(`http://localhost:${port}/slow`).on('error', () => {})
        await requestReceived
        req.destroy()

        await expect(lifecycle.drainInFlightRequests()).resolves.toBeUndefined()
    })
})
