import { TemplateTester } from '../../test/test-helpers'
import { template } from './teams.template'

const AZURE_LOGIC_URL =
    'https://prod-180.westus.logic.azure.com:443/workflows/abc/triggers/manual/paths/invoke?api-version=2016-06-01'
const createInputs = (overrides: Record<string, any> = {}): Record<string, any> => ({
    webhookUrl: AZURE_LOGIC_URL,
    text: "**max@posthog.com** triggered event: '$pageview'",
    ...overrides,
})
describe('microsoft teams template', () => {
    const tester = new TemplateTester(template)
    beforeEach(async () => {
        await tester.beforeEach()
    })
    it('posts the adaptive card', async () => {
        const response = await tester.invoke(createInputs())
        expect(response.error).toBeUndefined()
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(
            `
            {
              "body": "{"type":"message","attachments":[{"contentType":"application/vnd.microsoft.card.adaptive","contentUrl":null,"content":{"$schema":"http://adaptivecards.io/schemas/adaptive-card.json","type":"AdaptiveCard","version":"1.2","body":[{"type":"TextBlock","text":"**max@posthog.com** triggered event: ","wrap":true}]}}]}",
              "headers": {
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://prod-180.westus.logic.azure.com:443/workflows/abc/triggers/manual/paths/invoke?api-version=2016-06-01",
            }
        `
        )
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, { status: 200, body: '1' })
        expect(fetchResponse.error).toBeUndefined()
        expect(fetchResponse.finished).toBe(true)
    })
    /*
     * The URL guard is a security control, and Microsoft exposes webhooks under five
     * different host shapes. Each accepted form needs a case or a regex edit silently
     * locks customers out.
     */ it.each([
        AZURE_LOGIC_URL,
        'https://tenant.webhook.office.com/webhookb2/guid1/IncomingWebhook/guid2/guid3',
        'https://region.powerautomate.com/workflows/guid1/triggers/manual/guid2',
        'https://region.flow.microsoft.com/workflows/guid1/triggers/manual/guid2',
        'https://tenant.environment.api.powerplatform.com:443/powerautomate/automations/direct/workflows/guid1/triggers/manual/paths/invoke?api-version=1',
        'https://tenant.environment.api.powerplatform.com/powerautomate/automations/direct/workflows/guid1/triggers/manual/paths/invoke?api-version=1',
        'https://tenant.df.environment.api.powerplatform.com:443/powerautomate/automations/direct/cu/11/workflows/guid1/triggers/manual/paths/invoke?api-version=1',
    ])('accepts %s', async (webhookUrl) => {
        const response = await tester.invoke(createInputs({ webhookUrl }))
        expect(response.error).toBeUndefined()
        expect((response.invocation.queueParameters as any).url).toEqual(webhookUrl)
    })
    it.each(['https://webhook.site/def', `https://webhook.site/def#${AZURE_LOGIC_URL}`])(
        'rejects %s',
        async (webhookUrl) => {
            const response = await tester.invoke(createInputs({ webhookUrl }))
            expect(response.error).toContain('Invalid URL.')
            expect(response.invocation.queueParameters).toBeUndefined()
        }
    )
    it('errors on a non-2xx response', async () => {
        const response = await tester.invoke(createInputs())
        const result = await tester.invokeFetchResponse(response.invocation, { status: 400, body: 'Bad Request' })
        expect(result.error).toMatchInlineSnapshot(`"Failed to post message to Microsoft Teams: 400: Bad Request"`)
    })
})
