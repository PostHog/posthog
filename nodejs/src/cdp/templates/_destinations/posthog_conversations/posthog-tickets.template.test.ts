import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template as getTicketTemplate } from './posthog-get-ticket.template'
import { template as sendTicketMessageTemplate } from './posthog-send-ticket-message.template'
import { template as updateTicketTemplate } from './posthog-update-ticket.template'

const TICKET_UUID = '0198a5c1-2f6e-7c3a-9b41-b6d21c0aa111'

describe('posthog conversations ticket templates', () => {
    const cases = [
        {
            name: 'get ticket',
            template: getTicketTemplate,
            inputs: { ticket_id: TICKET_UUID },
            failurePrefix: 'Failed to fetch ticket (401):',
            actionId: undefined,
        },
        {
            name: 'update ticket',
            template: updateTicketTemplate,
            inputs: { ticket_id: TICKET_UUID, status: 'new' },
            failurePrefix: 'Failed to update ticket (401):',
            actionId: undefined,
        },
        {
            name: 'send message',
            template: sendTicketMessageTemplate,
            inputs: { ticket_id: TICKET_UUID, message: 'We are on it.' },
            failurePrefix: 'Failed to send message (401):',
            actionId: 'send_message',
        },
    ]

    describe.each(cases)('$name', ({ template, inputs, failurePrefix, actionId }) => {
        const tester = new TemplateTester(template)

        beforeEach(async () => {
            await tester.beforeEach()
        })

        it('surfaces the API error body when the request fails', async () => {
            // A revoked ticket claim or unprovisioned secret is the common failure here, and
            // the bare status code alone gave the customer nothing to act on.
            tester.mockInternalFetchResponse({ status: 401, body: { error: 'Invalid API key' } })

            let response = await tester.invoke(
                inputs,
                undefined,
                actionId ? { actionId, actionStepCount: 0 } : undefined
            )
            expect(response.error).toBeUndefined()
            response = await tester.resumeInvocation(response.invocation)

            expect(response.error).toEqual(`${failurePrefix} Invalid API key`)
        })

        it('returns the ticket body on success', async () => {
            tester.mockInternalFetchResponse({ status: 200, body: { id: TICKET_UUID, status: 'new' } })

            let response = await tester.invoke(
                inputs,
                undefined,
                actionId ? { actionId, actionStepCount: 0 } : undefined
            )
            response = await tester.resumeInvocation(response.invocation)

            expect(response.error).toBeUndefined()
            expect(response.finished).toBe(true)
            expect(response.execResult).toEqual({ id: TICKET_UUID, status: 'new' })
        })
    })

    describe('send message', () => {
        const tester = new TemplateTester(sendTicketMessageTemplate)

        beforeEach(async () => {
            await tester.beforeEach()
            tester.mockInternalFetchResponse({ status: 201, body: { id: 'message-1', is_private: false } })
        })

        const postedBody = (): { message: string; is_private: boolean; idempotency_key: string } => {
            const [, options] = tester.mockInternalFetch.mock.calls[0] as unknown as [string, { body: string }]
            return parseJSON(options.body)
        }

        it('posts a public reply by default and treats 201 as success', async () => {
            let response = await tester.invoke({ ticket_id: TICKET_UUID, message: 'We are on it.' }, undefined, {
                actionId: 'send_message',
                actionStepCount: 0,
            })
            response = await tester.resumeInvocation(response.invocation)

            expect(response.error).toBeUndefined()
            expect(response.finished).toBe(true)
            expect(postedBody()).toEqual({
                message: 'We are on it.',
                is_private: false,
                idempotency_key: expect.stringMatching(/:send_message:0$/),
            })
        })

        it('sends the private-note flag when the checkbox is on', async () => {
            await tester.invoke({ ticket_id: TICKET_UUID, message: 'Internal only', is_private: true }, undefined, {
                actionId: 'send_message',
                actionStepCount: 0,
            })
            expect(postedBody().is_private).toBe(true)
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
