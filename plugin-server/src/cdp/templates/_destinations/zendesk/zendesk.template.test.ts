import { TemplateTester } from '../../test/test-helpers'
import { template } from './zendesk.template'

describe('zendesk template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
        jest.useFakeTimers().setSystemTime(new Date('2025-01-01'))
    })

    const createInputs = (overrides = {}) => ({
        subdomain: 'zendeskhelp',
        admin_email: 'admin@zendesk.com',
        token: 'Q0UlvCexisMu6Je5MHG72ev16Tz68Tw8PRRpb5SX',
        email: 'max@posthog.com',
        name: 'Max',
        attributes: { phone: '0123456789', plan: 'starship-enterprise' },
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
              "body": "{\\"user\\":{\\"email\\":\\"max@posthog.com\\",\\"name\\":\\"Max\\",\\"skip_verify_email\\":true,\\"user_fields\\":{\\"phone\\":\\"0123456789\\",\\"plan\\":\\"starship-enterprise\\"}}}",
              "headers": Object {
                "Authorization": "Basic YWRtaW5AemVuZGVzay5jb20vdG9rZW46UTBVbHZDZXhpc011NkplNU1IRzcyZXYxNlR6NjhUdzhQUlJwYjVTWA==",
                "Content-Type": "application/json",
              },
              "method": "POST",
              "return_queue": "hog",
              "url": "https://zendeskhelp.zendesk.com/api/v2/users/create_or_update",
            }
        `)

        const fetchResponse = tester.invokeFetchResponse(response.invocation, {
            response: { status: 200, headers: {} },
            body: JSON.stringify({ ok: true }),
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it('should require identifier', async () => {
        const response = await tester.invoke(createInputs({ name: '' }))

        expect(response.finished).toBe(true)
        expect(response.logs.filter((l) => l.level === 'info')[0].message).toMatchInlineSnapshot(
            `"\`email\` or \`name\` input is empty. Not creating a contact."`
        )

        const response2 = await tester.invoke(createInputs({ email: '' }))

        expect(response2.finished).toBe(true)
        expect(response2.logs.filter((l) => l.level === 'info')[0].message).toMatchInlineSnapshot(
            `"\`email\` or \`name\` input is empty. Not creating a contact."`
        )
    })
})
