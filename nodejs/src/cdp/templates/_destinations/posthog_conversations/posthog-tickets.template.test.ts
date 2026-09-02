import { TemplateTester } from '../../test/test-helpers'
import { template as getTicketTemplate } from './posthog-get-ticket.template'
import { template as updateTicketTemplate } from './posthog-update-ticket.template'

describe('posthog conversations ticket templates', () => {
    const cases = [
        {
            name: 'get ticket',
            template: getTicketTemplate,
            inputs: { ticket_id: 'ticket-1' },
            failurePrefix: 'Failed to fetch ticket (401):',
        },
        {
            name: 'update ticket',
            template: updateTicketTemplate,
            inputs: { ticket_id: 'ticket-1', status: 'new' },
            failurePrefix: 'Failed to update ticket (401):',
        },
    ]

    describe.each(cases)('$name', ({ template, inputs, failurePrefix }) => {
        const tester = new TemplateTester(template)

        beforeEach(async () => {
            await tester.beforeEach()
        })

        it('surfaces the API error body when the request fails', async () => {
            let response = await tester.invoke(inputs)
            expect(response.error).toBeUndefined()
            expect(response.finished).toBe(false)

            // A rotated or deleted secret API key is the common failure here, and the bare
            // status code alone gave the customer nothing to act on.
            response = await tester.invokeFetchResponse(response.invocation, {
                status: 401,
                body: { error: 'Invalid API key' },
            })

            expect(response.error).toEqual(`${failurePrefix} Invalid API key`)
        })

        it('returns the ticket body on success', async () => {
            let response = await tester.invoke(inputs)
            expect(response.error).toBeUndefined()

            response = await tester.invokeFetchResponse(response.invocation, {
                status: 200,
                body: { id: 'ticket-1', status: 'new' },
            })

            expect(response.error).toBeUndefined()
            expect(response.finished).toBe(true)
            expect(response.execResult).toEqual({ id: 'ticket-1', status: 'new' })
        })
    })
})
