import { TemplateTester } from '../../test/test-helpers'
import { template } from './intercom.template'

describe('intercom template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
        jest.useFakeTimers().setSystemTime(new Date('2025-01-01'))
    })

    const createInputs = (overrides = {}) => ({
        access_token: 'TOKEN',
        email: 'example@posthog.com',
        host: 'api.intercom.com',
        ...overrides,
    })

    it('should invoke the function successfully', async () => {
        const response = await tester.invoke(createInputs())

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queue).toEqual('fetch')
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            Object {
              "body": "{\\"event_name\\":\\"event-name\\",\\"created_at\\":1704067200,\\"email\\":\\"example@posthog.com\\",\\"id\\":\\"distinct-id\\"}",
              "headers": Object {
                "Accept": "application/json",
                "Authorization": "Bearer TOKEN",
                "Content-Type": "application/json",
              },
              "method": "POST",
              "return_queue": "hog",
              "url": "https://api.intercom.com/events",
            }
        `)

        const fetchResponse = tester.invokeFetchResponse(response.invocation, {
            response: { status: 200, headers: {} },
            body: JSON.stringify({ status: 'success' }),
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
        expect(fetchResponse.logs.filter((l) => l.level === 'info')[0].message).toMatchInlineSnapshot(
            `"Event sent successfully!"`
        )
    })

    it('should exit if no email', async () => {
        const response = await tester.invoke(createInputs({ email: '' }))

        expect(response.finished).toBe(true)
        expect(response.logs.filter((l) => l.level === 'info')[0].message).toMatchInlineSnapshot(
            `"\`email\` input is empty. Skipping."`
        )
    })

    it('should handle missing contact error', async () => {
        const response = await tester.invoke(createInputs())

        const fetchResponse = tester.invokeFetchResponse(response.invocation, {
            response: { status: 404, headers: {} },
            body: JSON.stringify({ status: 'missing' }),
        })

        expect(fetchResponse.error).toBe('No existing contact found for email')
    })

    it('should handle other errors', async () => {
        const response = await tester.invoke(createInputs())

        const fetchResponse = tester.invokeFetchResponse(response.invocation, {
            response: { status: 400, headers: {} },
            body: JSON.stringify({
                type: 'error.list',
                request_id: '001dh0h1qb205el244gg',
                errors: [{ code: 'error', message: 'Other error' }],
            }),
        })

        expect(fetchResponse.error).toMatchInlineSnapshot(
            `"Error from intercom api (status 400): {'type': 'error.list', 'request_id': '001dh0h1qb205el244gg', 'errors': [{'code': 'error', 'message': 'Other error'}]}"`
        )
    })
})
