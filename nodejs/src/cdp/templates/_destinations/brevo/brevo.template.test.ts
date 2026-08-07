import { TemplateTester } from '../../test/test-helpers'
import { template } from './brevo.template'

const createInputs = (overrides: Record<string, any> = {}): Record<string, any> => ({
    apiKey: 'apikey12345',
    email: 'max@posthog.com',
    attributes: { EMAIL: 'max@posthog.com', FIRSTNAME: 'Max' },
    ...overrides,
})
describe('brevo template', () => {
    const tester = new TemplateTester(template)
    beforeEach(async () => {
        await tester.beforeEach()
    })
    it('creates the contact', async () => {
        const response = await tester.invoke(createInputs())
        expect(response.error).toBeUndefined()
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(
            `
            {
              "body": "{"email":"max@posthog.com","updateEnabled":true,"attributes":{"EMAIL":"max@posthog.com","FIRSTNAME":"Max"}}",
              "headers": {
                "Content-Type": "application/json",
                "api-key": "apikey12345",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://api.brevo.com/v3/contacts",
            }
        `
        )
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, { status: 201, body: { id: 42 } })
        expect(fetchResponse.error).toBeUndefined()
        expect(fetchResponse.finished).toBe(true)
    })
    it('skips the request when email is empty', async () => {
        const response = await tester.invoke(createInputs({ email: '' }))
        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(true)
        expect(response.invocation.queueParameters).toBeUndefined()
        expect(response.logs.filter((l) => l.level === 'info').map((l) => l.message)).toContain(
            'No email set. Skipping...'
        )
    })
    it('omits attributes with empty values', async () => {
        const response = await tester.invoke(createInputs({ attributes: { FIRSTNAME: 'Max', LASTNAME: '' } }))
        const body = (response.invocation.queueParameters as any).body
        expect(body).toContain('"FIRSTNAME":"Max"')
        expect(body).not.toContain('LASTNAME')
    })
    it('errors on a non-2xx response', async () => {
        const response = await tester.invoke(createInputs())
        const result = await tester.invokeFetchResponse(response.invocation, {
            status: 400,
            body: { code: 'invalid_parameter' },
        })
        expect(result.error).toMatchInlineSnapshot(
            `"Error from api.brevo.com (status 400): {'code': 'invalid_parameter'}"`
        )
    })
})
