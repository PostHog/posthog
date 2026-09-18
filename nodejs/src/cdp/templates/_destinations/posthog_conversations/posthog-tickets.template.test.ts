import { TemplateTester } from '../../test/test-helpers'
import { template as getTicketTemplate } from './posthog-get-ticket.template'
import { template as updateTicketTemplate } from './posthog-update-ticket.template'

const TICKET_UUID = '0198a5c1-2f6e-7c3a-9b41-b6d21c0aa111'

describe('posthog conversations ticket templates', () => {
    const cases = [
        {
            name: 'get ticket',
            template: getTicketTemplate,
            inputs: { ticket_id: TICKET_UUID },
            failurePrefix: 'Failed to fetch ticket (401):',
        },
        {
            name: 'update ticket',
            template: updateTicketTemplate,
            inputs: { ticket_id: TICKET_UUID, status: 'new' },
            failurePrefix: 'Failed to update ticket (401):',
        },
    ]

    describe.each(cases)('$name', ({ template, inputs, failurePrefix }) => {
        const tester = new TemplateTester(template)

        beforeEach(async () => {
            await tester.beforeEach()
        })

        it('surfaces the API error body when the request fails', async () => {
            // A revoked ticket claim or unprovisioned secret is the common failure here, and
            // the bare status code alone gave the customer nothing to act on.
            tester.mockInternalFetchResponse({ status: 401, body: { error: 'Invalid API key' } })

            let response = await tester.invoke(inputs)
            expect(response.error).toBeUndefined()
            response = await tester.resumeInvocation(response.invocation)

            expect(response.error).toEqual(`${failurePrefix} Invalid API key`)
        })

        it('returns the ticket body on success', async () => {
            tester.mockInternalFetchResponse({ status: 200, body: { id: TICKET_UUID, status: 'new' } })

            let response = await tester.invoke(inputs)
            response = await tester.resumeInvocation(response.invocation)

            expect(response.error).toBeUndefined()
            expect(response.finished).toBe(true)
            expect(response.execResult).toEqual({ id: TICKET_UUID, status: 'new' })
        })
    })

    describe('get ticket first_customer_message_text opt-in', () => {
        const tester = new TemplateTester(getTicketTemplate)

        beforeEach(async () => {
            await tester.beforeEach()
            tester.mockInternalFetchResponse({ status: 200, body: { id: TICKET_UUID } })
        })

        const fetchUrl = (): string => tester.mockInternalFetch.mock.calls[0][0] as string

        it('does not request the field by default', async () => {
            await tester.invoke({ ticket_id: TICKET_UUID })
            expect(fetchUrl()).not.toContain('include_first_customer_message_text')
        })

        it('appends the query param when opted in', async () => {
            await tester.invoke({ ticket_id: TICKET_UUID, include_first_customer_message_text: true })
            expect(fetchUrl()).toContain(
                `/internal/conversations/tickets/${TICKET_UUID}?include_first_customer_message_text=true`
            )
        })
    })
})
