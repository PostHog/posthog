import { TemplateTester } from '../../test/test-helpers'
import { template } from './engage.template'

const createInputs = (overrides: Record<string, any> = {}): Record<string, any> => ({
    public_key: 'PUBLIC_KEY',
    private_key: 'PRIVATE_KEY',
    ...overrides,
})
describe('engage template', () => {
    const tester = new TemplateTester(template)
    beforeEach(async () => {
        await tester.beforeEach()
    })
    it('forwards the event', async () => {
        const response = await tester.invoke(createInputs())
        expect(response.error).toBeUndefined()
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(
            `
            {
              "body": "{"uuid":"event-id","event":"event-name","distinct_id":"distinct-id","properties":{"$current_url":"https://example.com"},"timestamp":"2024-01-01T00:00:00Z","elements_chain":"","url":"https://us.posthog.com/projects/1/events/1234"}",
              "headers": {
                "Authorization": "Basic UFVCTElDX0tFWTpQUklWQVRFX0tFWQ==",
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://api.engage.so/posthog",
            }
        `
        )
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, { status: 200, body: {} })
        expect(fetchResponse.error).toBeUndefined()
        expect(fetchResponse.finished).toBe(true)
    })
    /*
     * The template ignores the response status entirely, so a rejected call finishes
     * cleanly. Locking that in makes it obvious if someone adds error handling later.
     */ it('ignores a non-2xx response', async () => {
        const response = await tester.invoke(createInputs())
        const result = await tester.invokeFetchResponse(response.invocation, {
            status: 401,
            body: { error: 'unauthorized' },
        })
        expect(result.error).toBeUndefined()
        expect(result.finished).toBe(true)
    })
})
