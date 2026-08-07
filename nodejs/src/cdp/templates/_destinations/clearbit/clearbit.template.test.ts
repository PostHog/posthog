import { TemplateTester } from '../../test/test-helpers'
import { template } from './clearbit.template'

const EXAMPLE_RESPONSE = {
    person: {
        id: '1234',
        name: { fullName: 'Max the Hedgehog', givenName: 'Max', familyName: 'the Hedgehog' },
        email: 'max@posthog.com',
    },
    company: { id: '1234', name: 'PostHog', legalName: 'PostHog Inc.', domain: 'posthog.com' },
}
const createInputs = (overrides: Record<string, any> = {}): Record<string, any> => ({
    api_key: 'API_KEY',
    email: 'example@posthog.com',
    ...overrides,
})
describe('clearbit template', () => {
    const tester = new TemplateTester(template)
    beforeEach(async () => {
        await tester.beforeEach()
    })
    it('looks the person up', async () => {
        const response = await tester.invoke(createInputs())
        expect(response.error).toBeUndefined()
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(
            `
            {
              "body": undefined,
              "headers": {
                "Authorization": "Bearer API_KEY",
              },
              "method": "GET",
              "type": "fetch",
              "url": "https://person-stream.clearbit.com/v2/combined/find?email=example@posthog.com",
            }
        `
        )
    })
    it.each([
        ['the email is empty', createInputs({ email: '' }), undefined],
        ['the person is already enriched', createInputs(), { person: { properties: { clearbit_enriched: true } } }],
    ])('does not look up when %s', async (_name, inputs, globals) => {
        const response = await tester.invoke(inputs, globals)
        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(true)
        expect(response.invocation.queueParameters).toBeUndefined()
    })
    it('captures a $set event when clearbit returns a person', async () => {
        const response = await tester.invoke(createInputs())
        const result = await tester.invokeFetchResponse(response.invocation, { status: 200, body: EXAMPLE_RESPONSE })
        expect(result.error).toBeUndefined()
        expect(result.logs.filter((l) => l.level === 'info').map((l) => l.message)).toContain(
            'Clearbit data found - sending event to PostHog'
        )
        expect(result.capturedPostHogEvents).toHaveLength(1)
        const captured = result.capturedPostHogEvents[0]
        expect(captured.event).toEqual('$set')
        expect(captured.distinct_id).toEqual('distinct-id')
        expect(captured.properties.$set_once).toEqual({
            person: EXAMPLE_RESPONSE.person,
            company: EXAMPLE_RESPONSE.company,
            clearbit_enriched: true,
        }) /* The executor stamps this on every captured event to bound self-referential loops. */
        expect(captured.properties.$hog_function_execution_count).toEqual(1)
    })
    it('captures nothing when clearbit returns no person', async () => {
        const response = await tester.invoke(createInputs())
        const result = await tester.invokeFetchResponse(response.invocation, { status: 200, body: {} })
        expect(result.error).toBeUndefined()
        expect(result.logs.filter((l) => l.level === 'info').map((l) => l.message)).toContain('No Clearbit data found')
        expect(result.capturedPostHogEvents).toEqual([])
    })
})
