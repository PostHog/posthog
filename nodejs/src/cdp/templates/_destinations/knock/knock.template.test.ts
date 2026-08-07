import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './knock.template'

const createInputs = (overrides: Record<string, any> = {}): Record<string, any> => ({
    webhookUrl: 'https://api.knock.app/v1/sources/posthog/events',
    userId: 'user-1',
    include_all_properties: false,
    attributes: { plan: 'paid' },
    ...overrides,
})
describe('knock template', () => {
    const tester = new TemplateTester(template)
    const parseBody = (response: any): Record<string, any> => parseJSON(response.invocation.queueParameters.body)
    beforeEach(async () => {
        await tester.beforeEach()
    })
    it('tracks the event', async () => {
        const response = await tester.invoke(createInputs())
        expect(response.error).toBeUndefined()
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"type":"track","event":"event-name","userId":"user-1","properties":{"plan":"paid"},"messageId":"event-id","timestamp":"2024-01-01T00:00:00Z"}",
              "headers": {
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://api.knock.app/v1/sources/posthog/events",
            }
        `)
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, { status: 200, body: {} })
        expect(fetchResponse.error).toBeUndefined()
        expect(fetchResponse.finished).toBe(true)
    })
    it.each([
        [false, { plan: 'paid' }],
        [true, { plan: 'paid', $current_url: 'https://example.com' }],
    ])('sends event properties when include_all_properties is %s', async (includeAll, expected) => {
        const response = await tester.invoke(createInputs({ include_all_properties: includeAll }))
        expect(parseBody(response).properties).toEqual(expected)
    })
    it('skips the request when the user id is empty', async () => {
        const response = await tester.invoke(createInputs({ userId: '' }))
        expect(response.finished).toBe(true)
        expect(response.invocation.queueParameters).toBeUndefined()
        expect(response.logs.filter((l) => l.level === 'info').map((l) => l.message)).toContain(
            'No User ID set. Skipping...'
        )
    })
    it('errors on a non-2xx response', async () => {
        const response = await tester.invoke(createInputs())
        const result = await tester.invokeFetchResponse(response.invocation, {
            status: 401,
            body: { message: 'unauthorized' },
        })
        expect(result.error).toMatchInlineSnapshot(`"Error from knock.app (status 401): {'message': 'unauthorized'}"`)
    })
})
