import { TemplateTester } from '../../test/test-helpers'
import { template as getAccountTemplate } from './posthog-get-account.template'
import { template as updateAccountPropertyTemplate } from './posthog-update-account-property.template'
import { template as updateAccountTemplate } from './posthog-update-account.template'

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
    ]

    describe.each(cases)('$name', ({ template, inputs, failurePrefix, successLog }) => {
        const tester = new TemplateTester(template)

        beforeEach(async () => {
            await tester.beforeEach()
        })

        it('surfaces the API error body when the request fails', async () => {
            let response = await tester.invoke(inputs)
            expect(response.error).toBeUndefined()
            expect(response.finished).toBe(false)

            response = await tester.invokeFetchResponse(response.invocation, {
                status: 400,
                body: { error: 'CSM: no relationship definition with this name' },
            })

            expect(response.error).toEqual(`${failurePrefix} CSM: no relationship definition with this name`)
        })

        it('prints a readable line on success', async () => {
            let response = await tester.invoke(inputs)
            expect(response.error).toBeUndefined()

            response = await tester.invokeFetchResponse(response.invocation, {
                status: 200,
                body: { id: 'account-id', external_id: 'acme-1' },
            })

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
            let response = await tester.invoke({ external_id: 'acme-1', tags: ['vip'] })

            response = await tester.invokeFetchResponse(response.invocation, { status, body })

            expect(response.error).toEqual(expected)
        })
    })
})
