import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './discord.template'

const createInputs = (overrides: Record<string, any> = {}): Record<string, any> => ({
    webhookUrl: 'https://discord.com/api/webhooks/00000000000000000/xxxxxxxxxxxxxx',
    content: 'Alert <@123456789> triggered',
    ...overrides,
})
describe('discord template', () => {
    const tester = new TemplateTester(template)
    const parseBody = (response: Awaited<ReturnType<typeof tester.invoke>>): Record<string, any> => {
        return parseJSON((response.invocation.queueParameters as any).body)
    }
    beforeEach(async () => {
        await tester.beforeEach()
    })
    it('posts the message', async () => {
        const response = await tester.invoke(createInputs())
        expect(response.error).toBeUndefined()
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"content":"Alert <@123456789> triggered","allowed_mentions":{"parse":[]}}",
              "headers": {
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://discord.com/api/webhooks/00000000000000000/xxxxxxxxxxxxxx",
            }
        `)
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, { status: 204, body: {} })
        expect(fetchResponse.error).toBeUndefined()
        expect(fetchResponse.finished).toBe(true)
    })
    it.each([
        ['none', []],
        ['roles_users', ['roles', 'users']],
        ['everyone', ['everyone', 'roles', 'users']],
    ])('maps allowedMentions %s to parse %j', async (choice, expectedParse) => {
        const response = await tester.invoke(createInputs({ allowedMentions: choice }))
        expect(parseBody(response).allowed_mentions).toEqual({ parse: expectedParse })
    }) /* The URL guard is a security control: it stops the webhook being pointed off-host. */
    it.each(['https://webhook.site/def', 'https://webhook.site/def#https://discord.com/api/webhooks/abc'])(
        'rejects the non-discord url %s',
        async (webhookUrl) => {
            const response = await tester.invoke(createInputs({ webhookUrl }))
            expect(response.error).toEqual(
                'Invalid URL. The URL should match the format: https://discord.com/api/webhooks/...'
            )
            expect(response.invocation.queueParameters).toBeUndefined()
        }
    )
    it('errors on a non-2xx response', async () => {
        const response = await tester.invoke(createInputs())
        const result = await tester.invokeFetchResponse(response.invocation, {
            status: 429,
            body: { message: 'rate limited' },
        })
        expect(result.error).toMatchInlineSnapshot(
            `"Failed to post message to Discord: 429: {'message': 'rate limited'}"`
        )
    })
})
