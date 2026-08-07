import { TemplateTester } from '../../test/test-helpers'
import { template } from './make.template'

const createInputs = (overrides: Record<string, any> = {}): Record<string, any> => ({
    webhookUrl: 'https://hook.xxx.make.com/xxxxxxxxxxxxxxxxxxxxxxxxxxxx',
    body: {
        data: {
            eventUuid: 'uuid-xxxxxxxxxxxxxxxxxxxxxxxxxxxx',
            event: '$pageview',
            teamId: 'teamId-xxxxxxxxxxxxxxxxxxxxxxxxxxxx',
            distinctId: 'distinctId-xxxxxxxxxxxxxxxxxxxxxxxxxxxx',
            properties: { uuid: 'person-uuid-xxxxxxxxxxxxxxxxxxxxxxxxxxxx' },
        },
    },
    ...overrides,
})
describe('make template', () => {
    const tester = new TemplateTester(template)
    beforeEach(async () => {
        await tester.beforeEach()
    })
    it('posts to the webhook', async () => {
        const response = await tester.invoke(createInputs())
        expect(response.error).toBeUndefined()
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(
            `
            {
              "body": "{"data":{"eventUuid":"uuid-xxxxxxxxxxxxxxxxxxxxxxxxxxxx","event":"$pageview","teamId":"teamId-xxxxxxxxxxxxxxxxxxxxxxxxxxxx","distinctId":"distinctId-xxxxxxxxxxxxxxxxxxxxxxxxxxxx","properties":{"uuid":"person-uuid-xxxxxxxxxxxxxxxxxxxxxxxxxxxx"}}}",
              "headers": {
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://hook.xxx.make.com/xxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            }
        `
        )
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, { status: 200, body: 'Accepted' })
        expect(fetchResponse.error).toBeUndefined()
        expect(fetchResponse.finished).toBe(true)
    }) /* The URL guard is a security control: it stops the webhook being pointed off-host. */
    it.each([
        'https://webhook.site/def',
        'https://webhook.site/def#https://hook.xxx.make.com/xxxxxxxxxxxxxxxxxxxxxxxxxxxx',
    ])('rejects the non-make url %s', async (webhookUrl) => {
        const response = await tester.invoke(createInputs({ webhookUrl }))
        expect(response.error).toEqual(
            'Invalid URL. The URL should match the format: https://hook.<region>.make.com/<hookUrl>'
        )
        expect(response.invocation.queueParameters).toBeUndefined()
    })
    it('errors on a non-2xx response', async () => {
        const response = await tester.invoke(createInputs())
        const result = await tester.invokeFetchResponse(response.invocation, { status: 410, body: 'Gone' })
        expect(result.error).toMatchInlineSnapshot(`"Error from make.com (status 410): Gone"`)
    })
})
