import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './intercom-event.template'

const createInputs = (overrides: Record<string, any> = {}): Record<string, any> => ({
    oauth: { access_token: 'ACCESS_TOKEN', 'app.region': 'US' },
    email: 'max@posthog.com',
    eventName: 'purchase',
    eventTime: '1234567890',
    include_all_properties: false,
    properties: { revenue: '50', currency: 'USD' },
    ...overrides,
})

describe('intercom event template', () => {
    const tester = new TemplateTester(template)

    const parseBody = (response: any): Record<string, any> => parseJSON(response.invocation.queueParameters.body)

    beforeEach(async () => {
        await tester.beforeEach()
    })

    it('searches for the contact, then sends the event', async () => {
        const response = await tester.invoke(createInputs(), {
            event: { event: 'purchase', timestamp: '1234567890' },
        })

        expect(response.error).toBeUndefined()
        expect((response.invocation.queueParameters as any).url).toEqual('https://api.intercom.io/contacts/search')

        const sent = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { total_count: 1, data: [{ id: '123' }] },
        })

        expect((sent.invocation.queueParameters as any).url).toEqual('https://api.intercom.io/events')
        expect(parseBody(sent)).toEqual({
            event_name: 'purchase',
            created_at: '1234567890',
            email: 'max@posthog.com',
            metadata: { revenue: '50', currency: 'USD' },
        })

        const done = await tester.invokeFetchResponse(sent.invocation, { status: 200, body: { ok: true } })
        expect(done.error).toBeUndefined()
        expect(done.finished).toBe(true)
    })

    it('sends event properties when include_all_properties is on', async () => {
        const response = await tester.invoke(createInputs({ include_all_properties: true }), {
            event: { event: 'purchase', properties: { plan: 'paid', $lib: 'web' } },
        })
        const sent = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { total_count: 1, data: [{ id: '123' }] },
        })

        expect(parseBody(sent).metadata.plan).toEqual('paid')
        /* $-prefixed event properties are PostHog internals and stay out of the payload. */
        expect(parseBody(sent).metadata.$lib).toBeUndefined()
    })

    it('skips the request when email is empty', async () => {
        const response = await tester.invoke(createInputs({ email: '' }))

        expect(response.finished).toBe(true)
        expect(response.invocation.queueParameters).toBeUndefined()
        expect(response.logs.filter((l) => l.level === 'info').map((l) => l.message)).toContain(
            'No email set. Skipping...'
        )
    })

    /* Unlike the contact template, this one needs exactly one match — zero is also fatal. */
    it.each([
        ['no contact matches', { total_count: 0, data: [] }],
        ['several contacts match', { total_count: 2, data: [{ id: '1' }, { id: '2' }] }],
    ])('throws when %s', async (_name, searchBody) => {
        const response = await tester.invoke(createInputs())
        const result = await tester.invokeFetchResponse(response.invocation, { status: 200, body: searchBody })

        expect(result.error).toEqual('No unique contact found. Skipping...')
    })

    it('throws when the event send fails', async () => {
        const response = await tester.invoke(createInputs())
        const sent = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { total_count: 1, data: [{ id: '123' }] },
        })
        const result = await tester.invokeFetchResponse(sent.invocation, { status: 400, body: { error: 'error' } })

        expect(result.error).toEqual("Error from intercom api (status 400): {'error': 'error'}")
    })
})
