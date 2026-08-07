import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './zendesk.template'

const createInputs = (overrides: Record<string, any> = {}): Record<string, any> => ({
    subdomain: 'zendeskhelp',
    admin_email: 'admin@zendesk.com',
    token: 'Q0UlvCexisMu6Je5MHG72ev16Tz68Tw8PRRpb5SX',
    email: 'max@posthog.com',
    name: 'Max',
    attributes: { phone: '0123456789', plan: 'starship-enterprise' },
    ...overrides,
})
describe('zendesk template', () => {
    const tester = new TemplateTester(template)
    beforeEach(async () => {
        await tester.beforeEach()
    })
    it('creates or updates the user', async () => {
        const response = await tester.invoke(createInputs(), { event: { event: '$identify' } })
        expect(response.error).toBeUndefined()
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"user":{"email":"max@posthog.com","name":"Max","skip_verify_email":true,"user_fields":{"phone":"0123456789","plan":"starship-enterprise"}}}",
              "headers": {
                "Authorization": "Basic YWRtaW5AemVuZGVzay5jb20vdG9rZW46UTBVbHZDZXhpc011NkplNU1IRzcyZXYxNlR6NjhUdzhQUlJwYjVTWA==",
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://zendeskhelp.zendesk.com/api/v2/users/create_or_update",
            }
        `)
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { user: { id: 1 } },
        })
        expect(fetchResponse.error).toBeUndefined()
        expect(fetchResponse.finished).toBe(true)
    })
    it.each(['name', 'email'])('skips the request when %s is empty', async (field) => {
        const response = await tester.invoke(createInputs({ [field]: '' }))
        expect(response.finished).toBe(true)
        expect(response.invocation.queueParameters).toBeUndefined()
        expect(response.logs.filter((l) => l.level === 'info').map((l) => l.message)).toContain(
            '`email` or `name` input is empty. Not creating a contact.'
        )
    }) /* email and name already have their own top-level slots, so they must not be duplicated. */
    it('keeps email and name out of user_fields', async () => {
        const response = await tester.invoke(
            createInputs({ attributes: { email: 'other@posthog.com', name: 'Other', plan: 'free' } })
        )
        const body = parseJSON((response.invocation.queueParameters as any).body)
        expect(body.user.user_fields).toEqual({ plan: 'free' })
        expect(body.user.email).toEqual('max@posthog.com')
    }) /*
     * The template ignores the response status, so a rejected call still finishes
     * cleanly. Locking that in makes it obvious if error handling is added later.
     */
    it('ignores a non-2xx response', async () => {
        const response = await tester.invoke(createInputs())
        const result = await tester.invokeFetchResponse(response.invocation, {
            status: 422,
            body: { error: 'RecordInvalid' },
        })
        expect(result.error).toBeUndefined()
        expect(result.finished).toBe(true)
    })
})
