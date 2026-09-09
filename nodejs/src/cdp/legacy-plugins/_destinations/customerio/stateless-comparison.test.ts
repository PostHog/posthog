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

    it.each([
        ['$is_identified is true', { $is_identified: true }, 'stateless_only'],
        ['$is_identified is the string true', { $is_identified: 'true' }, 'stateless_only'],
        [
            '$is_identified is false, despite a differing $device_id',
            { $is_identified: false, $device_id: 'a' },
            'match',
        ],
        [
            '$is_identified is absent and distinct_id differs from $device_id',
            { $device_id: 'anon-1' },
            'stateless_only',
        ],
        ['$is_identified is absent and distinct_id equals $device_id', { $device_id: 'user-1' }, 'match'],
    ])('derives identified when %s', async (_name, properties, expected) => {
        await expect(
            run({
                mode: 'Only send events from users that have been identified',
                stored: ['seen'],
                event: { properties },
            })
        ).resolves.toMatchObject({ identified: expected })
    })

    it('flags exists_already for a customer the storage has not seen before', async () => {
        await expect(run({ mode: 'Send all events', stored: [] })).resolves.toMatchObject({
            exists_already: 'stateless_only',
            tracked: 'match',
        })
    })
})
