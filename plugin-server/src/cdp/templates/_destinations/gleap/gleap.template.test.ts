import { TemplateTester } from '../../test/test-helpers'
import { template } from './gleap.template'

describe('gleap template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
        jest.useFakeTimers().setSystemTime(new Date('2025-01-01'))
    })

    const createInputs = (overrides = {}) => ({
        apiKey: 'uB6Jymn60NN5EEIWgiUzZx13geVlEx26',
        include_all_properties: false,
        userId: 'edad9282-25d0-4cf1-af0e-415535ee1161',
        attributes: { name: 'example', email: 'example@posthog.com' },
        ...overrides,
    })

    it('should invoke the function successfully', async () => {
        const response = await tester.invoke(createInputs(), {
            event: { event: '$identify' } as any,
        })

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queue).toEqual('fetch')
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            Object {
              "body": "{\\"userId\\":\\"edad9282-25d0-4cf1-af0e-415535ee1161\\",\\"name\\":\\"example\\",\\"email\\":\\"example@posthog.com\\"}",
              "headers": Object {
                "Api-Token": "uB6Jymn60NN5EEIWgiUzZx13geVlEx26",
                "Content-Type": "application/json",
                "User-Agent": "PostHog Gleap.io App",
              },
              "method": "POST",
              "return_queue": "hog",
              "url": "https://api.gleap.io/admin/identify",
            }
        `)

        const fetchResponse = tester.invokeFetchResponse(response.invocation, {
            response: { status: 200, headers: {} },
            body: JSON.stringify({ ok: true }),
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it('should include all properties if set', async () => {
        const response = await tester.invoke(createInputs({ include_all_properties: false }), {
            person: { properties: { account_status: 'paid' } } as any,
        })

        expect(JSON.parse(response.invocation.queueParameters?.body ?? '')).toEqual({
            userId: 'edad9282-25d0-4cf1-af0e-415535ee1161',
            name: 'example',
            email: 'example@posthog.com',
        })

        const response2 = await tester.invoke(createInputs({ include_all_properties: true }), {
            person: { properties: { account_status: 'paid' } } as any,
        })

        expect(JSON.parse(response2.invocation.queueParameters?.body ?? '')).toEqual({
            userId: 'edad9282-25d0-4cf1-af0e-415535ee1161',
            account_status: 'paid',
            name: 'example',
            email: 'example@posthog.com',
        })
    })

    it('should require identifier', async () => {
        const response = await tester.invoke(createInputs({ userId: '' }))

        expect(response.finished).toBe(true)
        expect(response.logs.filter((l) => l.level === 'info')[0].message).toMatchInlineSnapshot(
            `"No User ID set. Skipping..."`
        )
    })
})
