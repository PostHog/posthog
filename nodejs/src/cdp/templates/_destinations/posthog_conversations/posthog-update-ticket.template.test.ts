import { parseJSON } from '~/common/utils/json-parse'

import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult } from '../../../types'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './posthog-update-ticket.template'

describe('posthog update ticket template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
    })

    // The template's only side effect is the PATCH it queues, so its body is what every
    // assertion here is really about.
    const patchBody = (
        response: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>
    ): Record<string, any> => {
        const queueParameters = response.invocation.queueParameters
        if (queueParameters?.type !== 'fetch' || typeof queueParameters.body !== 'string') {
            throw new Error(`Expected a queued fetch with a body, got ${JSON.stringify(queueParameters)}`)
        }
        return parseJSON(queueParameters.body)
    }

    // A tag templated off a property that isn't set renders empty, and the API rejects a blank
    // tag with a 400 that fails the whole update.
    it.each([
        ['a missing person property', '{person.properties.plan}'],
        ['whitespace only', '   '],
        ['null', null],
    ])('keeps the rest of the update when a tag resolves to %s', async (_name, unresolvableTag) => {
        const response = await tester.invoke({
            ticket_id: 'ticket-1',
            status: 'open',
            priority: 'high',
            tags: [unresolvableTag, 'billing'],
        })

        expect(response.error).toBeUndefined()
        expect(patchBody(response)).toEqual({
            status: 'open',
            priority: 'high',
            tags: ['billing'],
            tags_mode: 'add',
        })
        expect(response.logs.map((log) => log.message)).toContainEqual(
            expect.stringContaining('Skipped 1 tag that resolved to no value')
        )
    })

    it('drops the tags update entirely when no tag resolves', async () => {
        const response = await tester.invoke({
            ticket_id: 'ticket-1',
            status: 'open',
            tags: ['{person.properties.plan}'],
        })

        expect(response.error).toBeUndefined()
        expect(patchBody(response)).toEqual({ status: 'open' })
    })

    it('sends resolved tags untouched', async () => {
        const response = await tester.invoke(
            {
                ticket_id: 'ticket-1',
                tags: ['plan_{person.properties.plan_name}', 'billing'],
                tags_mode: 'set',
            },
            { person: { properties: { plan_name: 'enterprise' } } }
        )

        expect(response.error).toBeUndefined()
        expect(patchBody(response)).toEqual({
            tags: ['plan_enterprise', 'billing'],
            tags_mode: 'set',
        })
    })
})
