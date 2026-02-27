import { EmailTrackingService } from '~/cdp/services/messaging/email-tracking.service'

jest.mock('~/utils/posthog', () => ({
    captureTeamEvent: jest.fn(),
    captureException: jest.fn(),
}))

describe('EmailTrackingService (SES reputation - rate breaches)', () => {
    let service: EmailTrackingService
    const hogFlow = { id: 'flow-1', team_id: 123 }
    const team = { id: hogFlow.team_id }

    function createRedisMock(initial: Record<string, string> = {}) {
        const store = new Map<string, string>(Object.entries(initial))

        const client = {
            incr: (key: string) => {
                const v = parseInt(store.get(key) ?? '0', 10) + 1
                store.set(key, String(v))
                return v
            },
            expire: () => 1,
            mget: (...keys: string[]) => keys.map((k) => store.get(k) ?? null),
            setnx: (key: string, val: string) => {
                if (!store.has(key)) {
                    store.set(key, val)
                    return 1
                }
                return 0
            },
        }

        return {
            useClient: (_opts: any, cb: any) => cb(client),
            __store: store,
        }
    }

    beforeEach(() => {
        const hogFunctionManager = { getHogFunction: jest.fn().mockResolvedValue(null) }
        const hogFlowManager = {
            getHogFlow: jest.fn((id: string) => Promise.resolve(id === hogFlow.id ? hogFlow : null)),
            disableHogFlow: jest.fn(() => true),
        }
        const hogFunctionMonitoringService = { queueAppMetric: jest.fn(), flush: jest.fn() }
        const teamManager = { getTeam: jest.fn(() => team) }

        // default redis (can be replaced per-test)
        const redis = createRedisMock()

        service = new EmailTrackingService(
            hogFunctionManager as any,
            hogFlowManager as any,
            hogFunctionMonitoringService as any,
            redis as any,
            teamManager as any
        )
    })

    it('disables flow when bounce rate breaches the configured threshold', async () => {
        const prefix = process.env.NODE_ENV === 'test' ? '@posthog-test/email-reputation' : '@posthog/email-reputation'

        // Pre-seed sends >= MIN_SENDS_FOR_RATE_CHECK and bounces such that bounceRate > BOUNCE_RATE_THRESHOLD
        const initial: any = {}
        initial[`${prefix}/${hogFlow.id}/sends`] = '250' // MIN_SENDS_FOR_RATE_CHECK
        initial[`${prefix}/${hogFlow.id}/bounces`] = '10' // bounceRate = 10/250 = 0.04 (> 0.02)
        initial[`${prefix}/${hogFlow.id}/complaints`] = '0'
        ;(service as any).redis = createRedisMock(initial) as any
        ;(service as any).sesWebhookHandler.handleWebhook = jest.fn().mockResolvedValue({
            status: 200,
            body: 'ok',
            metrics: [{ functionId: hogFlow.id, invocationId: 'inv-1', metricName: 'email_bounced' }],
        })

        await service.handleSesWebhook({ body: '{}', headers: {} } as any)

        expect((service as any).hogFlowManager.disableHogFlow).toHaveBeenCalledWith(hogFlow.id)
    })

    it('does not disable flow when sends below the MIN_SENDS_FOR_RATE_CHECK', async () => {
        const prefix = process.env.NODE_ENV === 'test' ? '@posthog-test/email-reputation' : '@posthog/email-reputation'

        const initial: Record<string, string> = {}
        initial[`${prefix}/${hogFlow.id}/sends`] = '10' // below MIN_SENDS_FOR_RATE_CHECK
        initial[`${prefix}/${hogFlow.id}/bounces`] = '1'
        initial[`${prefix}/${hogFlow.id}/complaints`] = '0'
        ;(service as any).redis = createRedisMock(initial) as any
        ;(service as any).sesWebhookHandler.handleWebhook = jest.fn().mockResolvedValue({
            status: 200,
            body: 'ok',
            metrics: [{ functionId: hogFlow.id, invocationId: 'inv-2', metricName: 'email_bounced' }],
        })

        await service.handleSesWebhook({ body: '{}', headers: {} } as any)

        expect((service as any).hogFlowManager.disableHogFlow).not.toHaveBeenCalled()
    })

    it('disables flow when complaint rate breaches the configured threshold', async () => {
        const prefix = process.env.NODE_ENV === 'test' ? '@posthog-test/email-reputation' : '@posthog/email-reputation'

        const initial: any = {}
        initial[`${prefix}/${hogFlow.id}/sends`] = '250' // MIN_SENDS_FOR_RATE_CHECK
        initial[`${prefix}/${hogFlow.id}/bounces`] = '0'
        initial[`${prefix}/${hogFlow.id}/complaints`] = '1' // complaintRate = 1/250 = 0.004 (> 0.001)
        ;(service as any).redis = createRedisMock(initial) as any
        ;(service as any).sesWebhookHandler.handleWebhook = jest.fn().mockResolvedValue({
            status: 200,
            body: 'ok',
            metrics: [{ functionId: hogFlow.id, invocationId: 'inv-3', metricName: 'email_blocked' }],
        })

        await service.handleSesWebhook({ body: '{}', headers: {} } as any)

        expect((service as any).hogFlowManager.disableHogFlow).toHaveBeenCalledWith(hogFlow.id)
    })

    it('does not disable flow when complaint rate is below threshold', async () => {
        const prefix = process.env.NODE_ENV === 'test' ? '@posthog-test/email-reputation' : '@posthog/email-reputation'

        const initial: Record<string, string> = {}
        initial[`${prefix}/${hogFlow.id}/sends`] = '100000'
        initial[`${prefix}/${hogFlow.id}/bounces`] = '0'
        initial[`${prefix}/${hogFlow.id}/complaints`] = '0'
        ;(service as any).redis = createRedisMock(initial) as any
        ;(service as any).sesWebhookHandler.handleWebhook = jest.fn().mockResolvedValue({
            status: 200,
            body: 'ok',
            metrics: [{ functionId: hogFlow.id, invocationId: 'inv-4', metricName: 'email_blocked' }],
        })

        await service.handleSesWebhook({ body: '{}', headers: {} } as any)

        expect((service as any).hogFlowManager.disableHogFlow).not.toHaveBeenCalled()
    })
})
