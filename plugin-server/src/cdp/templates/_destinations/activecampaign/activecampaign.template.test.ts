import { TemplateTester } from '../../test/test-helpers'
import { template } from './activecampaign.template'

describe('activecampaign template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
        jest.useFakeTimers().setSystemTime(new Date('2025-01-01'))
    })

    const createInputs = (overrides = {}) => ({
        account: '123456789',
        api_key: 'ac_api_key',
        email: 'test@posthog.com',
        first_name: 'Test',
        last_name: 'User',
        ...overrides,
    })

    it('should invoke the function successfully', async () => {
        const response = await tester.invoke(createInputs())

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queue).toEqual('fetch')
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            Object {
              "body": "{\\"contact\\":{\\"email\\":\\"test@posthog.com\\",\\"firstName\\":\\"Test\\",\\"lastName\\":\\"User\\"}}",
              "headers": Object {
                "Api-Token": "ac_api_key",
                "Content-Type": "application/json",
              },
              "method": "POST",
              "return_queue": "hog",
              "url": "https://123456789.api-us1.com/api/3/contacts",
            }
        `)

        const fetchResponse = tester.invokeFetchResponse(response.invocation, {
            response: { status: 200, headers: {} },
            body: JSON.stringify({ ok: true }),
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it('should require email', async () => {
        const response = await tester.invoke(createInputs({ email: '' }))

        expect(response.finished).toBe(true)
        expect(response.logs.filter((l) => l.level === 'info')[0].message).toMatchInlineSnapshot(
            `"No email set. Skipping..."`
        )
    })

    it('should handle errors', async () => {
        const response = await tester.invoke(createInputs())

        const fetchResponse = tester.invokeFetchResponse(response.invocation, {
            response: { status: 400, headers: {} },
            body: JSON.stringify({ errors: [{ title: 'Invalid input' }] }),
        })

        expect(fetchResponse.error).toMatchInlineSnapshot(
            `"Error from ActiveCampaign (status 400): {'errors': [{'title': 'Invalid input'}]}"`
        )
    })
})
