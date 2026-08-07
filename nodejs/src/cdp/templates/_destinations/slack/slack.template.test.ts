import { TemplateTester } from '../../test/test-helpers'
import { template } from './slack.template'

/*
 * `text` is set explicitly rather than left to its schema default. That default contains
 * single quotes, and the test helper compiles inputs by wrapping them in f'...', which
 * those quotes terminate early. Production parses the template properly, so the default
 * works there — it just cannot be exercised through this harness.
 */ const createInputs = (overrides: Record<string, any> = {}): Record<string, any> => ({
    slack_workspace: { access_token: 'xoxb-1234' },
    icon_emoji: ':hedgehog:',
    username: 'PostHog',
    channel: 'channel',
    blocks: [],
    text: '{person.name} triggered {event.event}',
    ...overrides,
})
describe('slack template', () => {
    const tester = new TemplateTester(template)
    beforeEach(async () => {
        await tester.beforeEach()
    })
    it('posts the message', async () => {
        const response = await tester.invoke(createInputs())
        expect(response.error).toBeUndefined()
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(
            `
            {
              "body": "{"channel":"channel","icon_emoji":":hedgehog:","username":"PostHog","blocks":[],"text":"person-name triggered event-name"}",
              "headers": {
                "Authorization": "Bearer xoxb-1234",
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://slack.com/api/chat.postMessage",
            }
        `
        )
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, { status: 200, body: { ok: true } })
        expect(fetchResponse.error).toBeUndefined()
        expect(fetchResponse.finished).toBe(true)
    }) /* Slack signals failure two ways, and the throw condition has a clause for each. */
    it.each([
        [{ status: 400, body: { ok: true } }, "Failed to post message to Slack: 400: {'ok': true}"],
        [{ status: 200, body: { ok: false } }, "Failed to post message to Slack: 200: {'ok': false}"],
    ])('throws on %o', async (fetchResponse, expectedError) => {
        const response = await tester.invoke(createInputs())
        const result = await tester.invokeFetchResponse(response.invocation, fetchResponse)
        expect(result.error).toEqual(expectedError)
    })
})
