import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template as createAccountTemplate } from './posthog-create-account.template'
import { template as getAccountTemplate } from './posthog-get-account.template'
import { template as tagAccountTemplate } from './posthog-tag-account.template'
import { template as updateAccountPropertyTemplate } from './posthog-update-account-property.template'
import { template as updateAccountRelationshipsTemplate } from './posthog-update-account-relationships.template'
import { template as updateAccountTemplate } from './posthog-update-account.template'

const REL_UUID = '0197f9f0-1111-0000-0000-000000000000'

const sentBody = (tester: TemplateTester): any =>
    parseJSON((tester.mockInternalFetch.mock.calls[0][1] as { body: string }).body)

describe('posthog customer analytics account templates', () => {
    const cases = [
        {
            name: 'get account',
            template: getAccountTemplate,
            inputs: { external_id: 'acme-1' },
            failurePrefix: 'Failed to fetch account (400):',
            successLog: 'Fetched account acme-1',
        },
        {
            name: 'create account',
            template: createAccountTemplate,
            inputs: { external_id: 'acme-1' },
            failurePrefix: 'Failed to create account (400):',
            // A 200 means the account already existed — creation is a no-op.
            successLog: 'Account acme-1 already exists — skipped creation',
        },
        {
            name: 'update account',
            template: updateAccountTemplate,
            inputs: { external_id: 'acme-1', tags: ['vip'], tags_mode: 'add' },
            failurePrefix: 'Failed to update account (400):',
            successLog: 'Updated account acme-1',
        },
        {
            name: 'update account property',
            template: updateAccountPropertyTemplate,
            inputs: { external_id: 'acme-1', properties: { '0197f9f0-0000-0000-0000-000000000000': 42 } },
            failurePrefix: 'Failed to update account properties (400):',
            successLog: 'Updated custom properties on account acme-1',
        },
        {
            name: 'tag account',
            template: tagAccountTemplate,
            inputs: { external_id: 'acme-1', tags: ['vip'], tags_mode: 'add' },
            failurePrefix: 'Failed to tag account (400):',
            successLog: 'Tagged account acme-1',
        },
        {
            name: 'update account relationships',
            template: updateAccountRelationshipsTemplate,
            inputs: { external_id: 'acme-1', relationships: { [REL_UUID]: { type: 'user', id: 42 } } },
            failurePrefix: 'Failed to update account relationships (400):',
            successLog: 'Updated relationships on account acme-1',
        },
    ]

    describe.each(cases)('$name', ({ template, inputs, failurePrefix, successLog }) => {
        const tester = new TemplateTester(template)

        beforeEach(async () => {
            await tester.beforeEach()
        })

        it('surfaces the API error body when the request fails', async () => {
            tester.mockInternalFetchResponse({
                status: 400,
                body: { error: 'CSM: no relationship definition with this name' },
            })

            let response = await tester.invoke(inputs)
            expect(response.error).toBeUndefined()
            response = await tester.resumeInvocation(response.invocation)

            expect(response.error).toEqual(`${failurePrefix} CSM: no relationship definition with this name`)
        })

        it('prints a readable line on success', async () => {
            tester.mockInternalFetchResponse({ status: 200, body: { id: 'account-id', external_id: 'acme-1' } })

            let response = await tester.invoke(inputs)
            response = await tester.resumeInvocation(response.invocation)

            expect(response.error).toBeUndefined()
            expect(response.finished).toBe(true)
            expect(response.logs.filter((log) => log.level === 'info').map((log) => log.message)).toContain(successLog)
        })
    })

    describe('error body without an error field', () => {
        const tester = new TemplateTester(updateAccountTemplate)

        beforeEach(async () => {
            await tester.beforeEach()
        })

        it.each([
            [
                'DRF-rendered error with a detail field',
                429,
                { detail: 'Request was throttled.' },
                'Failed to update account (429): Request was throttled.',
            ],
            ['non-JSON body', 503, 'upstream connect error', 'Failed to update account (503): upstream connect error'],
        ])('%s', async (_name, status, body, expected) => {
            tester.mockInternalFetchResponse({ status, body })

            let response = await tester.invoke({ external_id: 'acme-1', tags: ['vip'] })
            response = await tester.resumeInvocation(response.invocation)

            expect(response.error).toEqual(expected)
        })
    })

    describe('create account', () => {
        const tester = new TemplateTester(createAccountTemplate)

        beforeEach(async () => {
            await tester.beforeEach()
        })

        it('logs the created line on 201', async () => {
            tester.mockInternalFetchResponse({ status: 201, body: { id: 'account-id', external_id: 'acme-1' } })

            let response = await tester.invoke({ external_id: 'acme-1' })
            response = await tester.resumeInvocation(response.invocation)

            expect(sentBody(tester)).toEqual({ external_id: 'acme-1' })
            expect(response.error).toBeUndefined()
            expect(response.finished).toBe(true)
            expect(response.logs.filter((log) => log.level === 'info').map((log) => log.message)).toContain(
                'Created account acme-1'
            )
        })

        it('fails with a descriptive error when the event has no group of the account group type', async () => {
            const response = await tester.invoke({ external_id: '' })

            expect(response.error).toEqual(
                'Account external ID is required — the triggering event has no group of the configured account group type'
            )
        })
    })

    describe('update account property request body', () => {
        const tester = new TemplateTester(updateAccountPropertyTemplate)

        beforeEach(async () => {
            await tester.beforeEach()
        })

        it('sends an explicit property clear as API null', async () => {
            tester.mockInternalFetchResponse({ status: 200, body: { external_id: 'acme-1' } })

            const response = await tester.invoke({
                external_id: 'acme-1',
                properties: { '0197f9f0-0000-0000-0000-000000000000': { __posthog_clear_property: true } },
            })

            expect(response.error).toBeUndefined()
            expect(sentBody(tester).properties).toEqual({ '0197f9f0-0000-0000-0000-000000000000': null })
        })

        it('rejects a property template that resolves to null', async () => {
            const response = await tester.invoke({
                external_id: 'acme-1',
                properties: { '0197f9f0-0000-0000-0000-000000000000': '{event.properties.plan}' },
            })

            expect(response.error).toContain("received null for property '0197f9f0-0000-0000-0000-000000000000'")
            expect(tester.mockInternalFetch).not.toHaveBeenCalled()
        })
    })

    describe('update account relationships request body', () => {
        const tester = new TemplateTester(updateAccountRelationshipsTemplate)

        beforeEach(async () => {
            await tester.beforeEach()
        })

        it('sends relationship assignments keyed by UUID in the request body', async () => {
            tester.mockInternalFetchResponse({ status: 200, body: { external_id: 'acme-1' } })

            const response = await tester.invoke({
                external_id: 'acme-1',
                relationships: { [REL_UUID]: { type: 'user', id: 42 } },
            })

            expect(response.error).toBeUndefined()
            expect(sentBody(tester).relationships).toEqual({ [REL_UUID]: { type: 'user', id: 42 } })
        })
    })
})
