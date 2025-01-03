import { TemplateTester } from '../../test/test-helpers'
import { template } from './slack.template'

describe('slack template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
        jest.useFakeTimers().setSystemTime(new Date('2025-01-01'))
    })

    const defaultInputs = {
        slack_workspace: {
            access_token: 'xoxb-1234',
        },
        icon_emoji: ':hedgehog:',
        username: 'PostHog',
        channel: 'channel',
        blocks: [],
    }

    it('should invoke the function successfully', async () => {
        const response = await tester.invoke(defaultInputs)

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queue).toEqual('fetch')
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            Object {
              "body": "{\\"channel\\":\\"channel\\",\\"icon_emoji\\":\\":hedgehog:\\",\\"username\\":\\"PostHog\\",\\"blocks\\":[],\\"text\\":{\\"value\\":\\"*person-name* triggered event: \\"}}",
              "headers": Object {
                "Authorization": "Bearer xoxb-1234",
                "Content-Type": "application/json",
              },
              "method": "POST",
              "return_queue": "hog",
              "url": "https://slack.com/api/chat.postMessage",
            }
        `)

        const fetchResponse = tester.invokeFetchResponse(response.invocation, {
            response: { status: 200, headers: {} },
            body: JSON.stringify({ ok: true }),
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it('should throw error on bad status', async () => {
        const response = await tester.invoke(defaultInputs)

        const fetchResponse = tester.invokeFetchResponse(response.invocation, {
            response: { status: 400, headers: {} },
            body: JSON.stringify({ ok: true }),
        })

        expect(fetchResponse.error).toMatchInlineSnapshot(`"Failed to post message to Slack: 400: {'ok': true}"`)
    })

    it('should throw error when slack response is not ok', async () => {
        const response = await tester.invoke(defaultInputs)

        const fetchResponse = tester.invokeFetchResponse(response.invocation, {
            response: { status: 200, headers: {} },
            body: JSON.stringify({ ok: false }),
        })

        expect(fetchResponse.error).toMatchInlineSnapshot(`"Failed to post message to Slack: 200: {'ok': false}"`)
    })
})
