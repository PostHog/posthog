import { pino } from 'pino'

import { createNodeService } from './service.js'

describe('createNodeService', () => {
    it('keeps readiness closed until startup and reports dependency failures', async () => {
        let databaseReady: boolean | 'throws' = true
        const service = createNodeService({
            name: 'test-service',
            logger: pino({ enabled: false }),
            readinessChecks: {
                database: () => {
                    if (databaseReady === 'throws') {
                        throw new Error('private connection detail')
                    }
                    return databaseReady ? { status: 'ok' } : { status: 'error', message: 'down' }
                },
            },
        })

        expect((await service.app.request('/_ready')).status).toBe(503)

        service.state.ready = true
        expect((await service.app.request('/_ready')).status).toBe(200)

        databaseReady = false
        const failedResponse = await service.app.request('/_ready')
        expect(failedResponse.status).toBe(503)
        expect(await failedResponse.json()).toEqual({
            status: 'error',
            checks: { database: { status: 'error', message: 'down' } },
        })

        databaseReady = 'throws'
        expect(await (await service.app.request('/_ready')).json()).toEqual({
            status: 'error',
            checks: { database: { status: 'error' } },
        })
    })

    it('uses route templates in HTTP metrics instead of request paths', async () => {
        const service = createNodeService({ name: 'test-service', logger: pino({ enabled: false }) })
        service.app.get('/projects/:projectId', (context) =>
            context.json({ projectId: context.req.param('projectId') })
        )

        const response = await service.app.request('/projects/123456')
        expect(response.status).toBe(200)
        expect(response.headers.get('x-content-type-options')).toBe('nosniff')
        expect(response.headers.get('x-request-id')).toBeTruthy()

        const metrics = await service.metrics.registry.metrics()
        expect(metrics).toContain('route="/projects/:projectId"')
        expect(metrics).not.toContain('123456')
    })

    it('turns unhandled route errors into a stable response', async () => {
        const service = createNodeService({ name: 'test-service', logger: pino({ enabled: false }) })
        service.app.get('/failure', () => {
            throw new Error('private failure detail')
        })

        const response = await service.app.request('/failure')
        expect(response.status).toBe(500)
        expect(await response.json()).toEqual({ error: 'Internal server error' })
    })
})
