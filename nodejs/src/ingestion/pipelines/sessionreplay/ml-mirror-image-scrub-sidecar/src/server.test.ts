import { once } from 'node:events'
import type { AddressInfo } from 'node:net'

import { startServer } from './server.ts'

const PNG = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAACgAAAAoCAIAAAADnC86AAAACXBIWXMAAAPoAAAD6AG1e1JrAAAAR0lEQVR4nO3YsQkAIAxEUeu//1A3ljvY2DywD0iSR+6svryjcL56mivjlAUyKzNIhMWwGBaHxbAYFodF12IO80QRE770HDddvGtfTNaUfqIAAAAASUVORK5CYII=',
    'base64'
)

describe('image-scrub sidecar server', () => {
    let base: string
    let metricsBase: string
    let servers: ReturnType<typeof startServer>

    beforeAll(async () => {
        servers = startServer(0, 0, 4, 1024)
        await Promise.all([once(servers.scrub, 'listening'), once(servers.metrics, 'listening')])
        base = `http://127.0.0.1:${(servers.scrub.address() as AddressInfo).port}`
        metricsBase = `http://127.0.0.1:${(servers.metrics.address() as AddressInfo).port}`
    })
    afterAll((done) => {
        let remaining = 2
        for (const server of [servers.scrub, servers.metrics]) {
            server.closeAllConnections()
            server.close(() => --remaining === 0 && done())
        }
    })

    it('scrubs posted image bytes into different (blurred) bytes', async () => {
        const res = await fetch(`${base}/scrub`, { method: 'POST', body: PNG })
        expect(res.status).toBe(200)
        const out = Buffer.from(await res.arrayBuffer())
        expect(out.length).toBeGreaterThan(0)
        expect(out.equals(PNG)).toBe(false)
    })

    it('422s on undecodable bytes so the consumer skips them instead of retrying forever', async () => {
        const res = await fetch(`${base}/scrub`, { method: 'POST', body: Buffer.from('not-an-image') })
        expect(res.status).toBe(422)
    })

    it('413s on a body over the size cap so the consumer skips it', async () => {
        const res = await fetch(`${base}/scrub`, { method: 'POST', body: Buffer.alloc(2048) })
        expect(res.status).toBe(413)
    })

    it('422s a request with no body', async () => {
        const res = await fetch(`${base}/scrub`, { method: 'POST' })
        expect(res.status).toBe(422)
    })

    it('422s a truncated image (fails mid-decode, not just at the header)', async () => {
        const res = await fetch(`${base}/scrub`, { method: 'POST', body: PNG.subarray(0, 40) })
        expect(res.status).toBe(422)
    })

    it('serves health + metrics on the metrics listener, not the scrub listener', async () => {
        expect((await fetch(`${metricsBase}/_health`)).status).toBe(200)
        const metrics = await fetch(`${metricsBase}/metrics`)
        expect(metrics.status).toBe(200)
        expect(await metrics.text()).toContain('ml_mirror_image_scrub_scrubbed_total')
    })

    it('does not expose /scrub on the metrics listener', async () => {
        const res = await fetch(`${metricsBase}/scrub`, { method: 'POST', body: PNG })
        expect(res.status).toBe(404)
    })

    it('does not serve health or metrics on the scrub listener', async () => {
        expect((await fetch(`${base}/_health`)).status).toBe(404)
        expect((await fetch(`${base}/_ready`)).status).toBe(404)
        expect((await fetch(`${base}/metrics`)).status).toBe(404)
    })
})
