import { TemplateTester } from '../../test/test-helpers'
import { template } from './activecampaign.template'

const createInputs = (overrides: Record<string, any> = {}): Record<string, any> => ({
    accountName: 'posthog',
    apiKey: 'API_KEY',
    email: 'max@posthog.com',
    firstName: 'max',
    attributes: { '1': 'PostHog', '2': 'posthog.com' },
    ...overrides,
})
describe('activecampaign template', () => {
    const tester = new TemplateTester(template)
    beforeEach(async () => {
        await tester.beforeEach()
    })
    it('syncs the contact', async () => {
        const response = await tester.invoke(createInputs(), { event: { event: '$identify' } })
        expect(response.error).toBeUndefined()
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(
            `
            {
              "body": "{"contact":{"email":"max@posthog.com","fieldValues":[{"field":"1","value":"PostHog"},{"field":"2","value":"posthog.com"}],"firstName":"max"}}",
              "headers": {
                "Api-Token": "API_KEY",
                "content-type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://posthog.api-us1.com/api/3/contact/sync",
            }
        `
        )
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { contact: { id: '1' } },
        })
        expect(fetchResponse.error).toBeUndefined()
        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.logs.filter((l) => l.level === 'info').map((l) => l.message)).toContain(
            'Contact has been created or updated successfully!'
        )
    })
    it('skips the request when email is empty', async () => {
        const response = await tester.invoke(createInputs({ email: '' }))
        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(true)
        expect(response.invocation.queueParameters).toBeUndefined()
        expect(response.logs.filter((l) => l.level === 'info').map((l) => l.message)).toContain(
            '`email` input is empty. Not creating a contact.'
        )
    })
    it('drops attributes with empty values', async () => {
        const response = await tester.invoke(createInputs({ attributes: { '1': 'PostHog', '2': '', '3': null } }))
        const body = (response.invocation.queueParameters as any).body
        expect(body).toContain('"fieldValues":[{"field":"1","value":"PostHog"}]')
    })
    it('errors on a non-2xx response', async () => {
        const response = await tester.invoke(createInputs())
        const result = await tester.invokeFetchResponse(response.invocation, { status: 400, body: { message: 'nope' } })
        expect(result.error).toMatchInlineSnapshot(`"Error from posthog.api-us1.com (status 400): {'message': 'nope'}"`)
    })
})
