import { TemplateTester } from '../../test/test-helpers'
import { template } from './attio.template'

const createInputs = (overrides: Record<string, any> = {}): Record<string, any> => ({
    apiKey: 'apikey12345',
    email: 'max@posthog.com',
    personAttributes: { name: 'Max', job_title: 'Mascot' },
    ...overrides,
})
describe('attio template', () => {
    const tester = new TemplateTester(template)
    beforeEach(async () => {
        await tester.beforeEach()
    })
    it('upserts the person record', async () => {
        const response = await tester.invoke(createInputs())
        expect(response.error).toBeUndefined()
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(
            `
            {
              "body": "{"data":{"values":{"email_addresses":[{"email_address":"max@posthog.com"}],"name":"Max","job_title":"Mascot"}}}",
              "headers": {
                "Authorization": "Bearer apikey12345",
                "Content-Type": "application/json",
              },
              "method": "PUT",
              "type": "fetch",
              "url": "https://api.attio.com/v2/objects/people/records?matching_attribute=email_addresses",
            }
        `
        )
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, { status: 200, body: { ok: true } })
        expect(fetchResponse.error).toBeUndefined()
        expect(fetchResponse.finished).toBe(true)
    })
    it('omits person attributes with empty values', async () => {
        const response = await tester.invoke(createInputs({ personAttributes: { name: 'Max', job_title: '' } }))
        const body = (response.invocation.queueParameters as any).body
        expect(body).toContain('"name":"Max"')
        expect(body).not.toContain('job_title')
    })
    it('errors on a non-2xx response', async () => {
        const response = await tester.invoke(createInputs())
        const result = await tester.invokeFetchResponse(response.invocation, {
            status: 400,
            body: { error: 'bad request' },
        })
        expect(result.error).toMatchInlineSnapshot(`"Error from api.attio.com (status 400): {'error': 'bad request'}"`)
    })
})
