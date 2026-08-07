import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './gleap.template'

const createInputs = (overrides: Record<string, any> = {}): Record<string, any> => ({
    apiKey: 'uB6Jymn60NN5EEIWgiUzZx13geVlEx26',
    include_all_properties: false,
    userId: 'edad9282-25d0-4cf1-af0e-415535ee1161',
    attributes: { name: 'example', email: 'example@posthog.com' },
    ...overrides,
})
describe('gleap template', () => {
    const tester = new TemplateTester(template)
    const parseBody = (response: Awaited<ReturnType<typeof tester.invoke>>): Record<string, any> => {
        return parseJSON((response.invocation.queueParameters as any).body)
    }
    beforeEach(async () => {
        await tester.beforeEach()
    })
    it('identifies the user', async () => {
        const response = await tester.invoke(createInputs(), { event: { event: '$identify' } })
        expect(response.error).toBeUndefined()
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"userId":"edad9282-25d0-4cf1-af0e-415535ee1161","name":"example","email":"example@posthog.com"}",
              "headers": {
                "Api-Token": "uB6Jymn60NN5EEIWgiUzZx13geVlEx26",
                "Content-Type": "application/json",
                "User-Agent": "PostHog Gleap.io App",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://api.gleap.io/admin/identify",
            }
        `)
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, { status: 200, body: {} })
        expect(fetchResponse.error).toBeUndefined()
        expect(fetchResponse.finished).toBe(true)
    })
    it.each([
        [false, { userId: 'edad9282-25d0-4cf1-af0e-415535ee1161', name: 'example', email: 'example@posthog.com' }],
        [
            true,
            {
                userId: 'edad9282-25d0-4cf1-af0e-415535ee1161',
                email: 'example@posthog.com',
                account_status: 'paid',
                name: 'example',
            },
        ],
    ])('sends person properties when include_all_properties is %s', async (includeAll, expected) => {
        const response = await tester.invoke(createInputs({ include_all_properties: includeAll }), {
            person: { properties: { account_status: 'paid', email: 'example@posthog.com' } },
        })
        expect(parseBody(response)).toEqual(expected)
    })
    it('skips the request when the user id is empty', async () => {
        const response = await tester.invoke(createInputs({ userId: '' }))
        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(true)
        expect(response.invocation.queueParameters).toBeUndefined()
        expect(response.logs.filter((l) => l.level === 'info').map((l) => l.message)).toContain(
            'No User ID set. Skipping...'
        )
    })
    it('errors on a non-2xx response', async () => {
        const response = await tester.invoke(createInputs())
        const result = await tester.invokeFetchResponse(response.invocation, {
            status: 400,
            body: { message: 'bad token' },
        })
        expect(result.error).toMatchInlineSnapshot(`"Error from gleap.io (status 400): {'message': 'bad token'}"`)
    })
})
