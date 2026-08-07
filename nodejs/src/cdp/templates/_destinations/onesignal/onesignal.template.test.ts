import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './onesignal.template'

const createInputs = (overrides: Record<string, any> = {}): Record<string, any> => ({
    appId: 'APP_ID',
    apiKey: 'API_KEY',
    externalId: 'user-1',
    eventName: 'purchase',
    eventTimestamp: '2024-01-01T00:00:00Z',
    eventProperties: { revenue: 50 },
    ...overrides,
})
describe('onesignal template', () => {
    const tester = new TemplateTester(template)
    beforeEach(async () => {
        await tester.beforeEach()
    })
    it('sends the custom event', async () => {
        const response = await tester.invoke(createInputs())
        expect(response.error).toBeUndefined()
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"events":[{"external_id":"user-1","name":"purchase","properties":{"revenue":50},"timestamp":"2024-01-01T00:00:00Z"}]}",
              "headers": {
                "Authorization": "Key API_KEY",
                "Content-Type": "application/json",
                "OneSignal-Usage": "PostHog | Partner Integration",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://api.onesignal.com/apps/APP_ID/custom_events",
            }
        `)
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, { status: 202, body: {} })
        expect(fetchResponse.error).toBeUndefined()
        expect(fetchResponse.finished).toBe(true)
    }) /* With no configured properties the template falls back to the event's own. */
    it('falls back to the event properties when none are configured', async () => {
        const response = await tester.invoke(createInputs({ eventProperties: {} }), {
            event: { properties: { plan: 'paid' } },
        })
        const body = parseJSON((response.invocation.queueParameters as any).body)
        expect(body.events[0].properties.plan).toEqual('paid')
    })
    it('errors on a non-2xx response', async () => {
        const response = await tester.invoke(createInputs())
        const result = await tester.invokeFetchResponse(response.invocation, {
            status: 400,
            body: { errors: ['bad app id'] },
        })
        expect(result.error).toMatchInlineSnapshot(`"Error sending event: 400 {'errors': ['bad app id']}"`)
    })
})
