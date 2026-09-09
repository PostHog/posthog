import { register } from 'prom-client'

import { ProcessedPluginEvent } from '~/plugin-scaffold'

import { onEvent, setupPlugin } from './index'

describe('customer.io stateless status comparison', () => {
    const metricName = 'cdp_customerio_stateless_customer_comparison_total'

    const run = async ({
        mode,
        stored,
        person,
        event,
    }: {
        mode?: string
        stored: string[]
        person?: Record<string, any>
        event?: Partial<ProcessedPluginEvent>
    }): Promise<Record<string, string>> => {
        const meta: any = {
            config: { customerioSiteId: 'site', customerioToken: 'token', sendEventsFromAnonymousUsers: mode },
            global: {},
            logger: { debug: jest.fn(), warn: jest.fn(), log: jest.fn(), error: jest.fn() },
            fetch: jest.fn().mockResolvedValue({ status: 200, json: () => Promise.resolve({}) }),
            storage: { get: jest.fn().mockResolvedValue(stored), set: jest.fn() },
            person: person ? { id: 'p', name: 'p', url: '', properties: person } : undefined,
        }

        await setupPlugin(meta)
        await onEvent(
            {
                distinct_id: 'user-1',
                event: 'purchase',
                properties: {},
                team_id: 1,
                uuid: 'uuid',
                ip: null,
                ...event,
            } as ProcessedPluginEvent,
            meta
        )

        const metric = (await register.getMetricsAsJSON()).find((m) => m.name === metricName) as any
        return Object.fromEntries(metric.values.map((v: any) => [v.labels.field, v.labels.result]))
    }

    beforeEach(() => {
        register.getSingleMetric(metricName)?.reset()
    })

    it('agrees when person properties carry the email the stored status already recorded', async () => {
        await expect(
            run({
                mode: 'Only send events from users with emails',
                stored: ['seen', 'with_email'],
                person: { email: 'a@example.com' },
            })
        ).resolves.toMatchObject({ with_email: 'match', tracked: 'match' })
    })

    it('flags with_email when the person has an email the storage never saw', async () => {
        await expect(
            run({
                mode: 'Only send events from users with emails',
                stored: ['seen'],
                person: { email: 'a@example.com' },
            })
        ).resolves.toMatchObject({ with_email: 'stateless_only', tracked: 'stateless_only' })
    })

    it('derives identified from a distinct_id that differs from $device_id', async () => {
        await expect(
            run({
                mode: 'Only send events from users that have been identified',
                stored: ['seen'],
                event: { properties: { $device_id: 'anon-1' } },
            })
        ).resolves.toMatchObject({ identified: 'stateless_only' })
    })

    it('does not derive identified for an anonymous distinct_id', async () => {
        await expect(
            run({
                mode: 'Only send events from users that have been identified',
                stored: ['seen'],
                event: { distinct_id: 'anon-1', properties: { $device_id: 'anon-1' } },
            })
        ).resolves.toMatchObject({ identified: 'match' })
    })

    it('flags exists_already for a customer the storage has not seen before', async () => {
        await expect(run({ mode: 'Send all events', stored: [] })).resolves.toMatchObject({
            exists_already: 'stateless_only',
            tracked: 'match',
        })
    })
})
