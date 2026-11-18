import { parseJSON } from '~/common/utils/json-parse'
import { ProcessedPluginEvent } from '~/plugin-scaffold'

import { onEvent, setupPlugin } from './index'

describe('customer.io customer status', () => {
    const run = async ({
        mode,
        person,
        event,
    }: {
        mode: string
        person?: Record<string, any>
        event?: Partial<ProcessedPluginEvent>
    }): Promise<{ sent: boolean; identifyBody: Record<string, any> | undefined }> => {
        const calls: { url: string; body: any }[] = []
        const meta: any = {
            config: { customerioSiteId: 'site', customerioToken: 'token', sendEventsFromAnonymousUsers: mode },
            global: {},
            logger: { debug: jest.fn(), warn: jest.fn(), log: jest.fn(), error: jest.fn() },
            fetch: jest.fn().mockImplementation((url: string, params: any) => {
                calls.push({ url, body: params.body ? parseJSON(params.body) : undefined })
                return Promise.resolve({ status: 200, json: () => Promise.resolve({}) })
            }),
            person: person ? { id: 'p', name: 'p', url: '', properties: person } : undefined,
        }

        await setupPlugin(meta)
        calls.length = 0

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

        const identify = calls.find((c) => c.url.includes('/customers/') && !c.url.endsWith('/events'))
        return { sent: calls.length > 0, identifyBody: identify?.body }
    }

    const WITH_EMAIL = 'Only send events from users with emails'
    const IDENTIFIED = 'Only send events from users that have been identified'

    test.each([
        ['person carries an email the event does not', WITH_EMAIL, { email: 'a@example.com' }, {}, true],
        ['neither event nor person carries an email', WITH_EMAIL, undefined, {}, false],
        ['$is_identified is true', IDENTIFIED, undefined, { properties: { $is_identified: true } }, true],
        ['$is_identified is the string true', IDENTIFIED, undefined, { properties: { $is_identified: 'true' } }, true],
        ['$is_identified is false', IDENTIFIED, undefined, { properties: { $is_identified: false } }, false],
        [
            // Cookieless events always get a device id that differs from the distinct id
            'the event is anonymous cookieless',
            IDENTIFIED,
            undefined,
            { distinct_id: 'cookieless_a', properties: { $device_id: 'cookielessd_b' } },
            false,
        ],
        ['no gate is configured', 'Send all events', undefined, {}, true],
    ])('sends %s: %s', async (_name, mode, person, event, expected) => {
        const { sent } = await run({ mode: mode as string, person: person as any, event: event as any })
        expect(sent).toBe(expected)
    })

    it('identifies the customer by the person email when the event has none', async () => {
        const { identifyBody } = await run({ mode: WITH_EMAIL, person: { email: 'a@example.com' } })

        expect(identifyBody).toMatchObject({ email: 'a@example.com' })
    })
})
