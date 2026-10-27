import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './posthog-slack-dm-team-member.template'

const INPUTS = {
    slack_workspace: { $integration_id: 42, access_token: 'xoxb-test' },
    recipient: 'ada@example.com',
    text: 'Ticket needs you',
    button_url: 'https://app.example.com/tickets/1',
    button_text: 'View ticket',
}
const WORKFLOW_STEP = { actionId: 'dm_member', actionStepCount: 0, hogFlow: { id: 'flow-1' } }

describe('message team member on Slack template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
    })

    it('sends the workspace, message and a per-step idempotency key to the workflow route', async () => {
        tester.mockInternalFetchResponse({ status: 200, body: { outcome: 'sent', detail: 'The message was sent.' } })

        let response = await tester.invoke(INPUTS, undefined, WORKFLOW_STEP)
        response = await tester.resumeInvocation(response.invocation)

        const [url, options] = tester.mockInternalFetch.mock.calls[0] as unknown as [string, { body: string }]
        expect(url).toContain('/workflow_slack_team_member_messages/')
        expect(parseJSON(options.body)).toEqual({
            integration_id: 42,
            recipient: 'ada@example.com',
            text: 'Ticket needs you',
            button_url: 'https://app.example.com/tickets/1',
            button_text: 'View ticket',
            idempotency_key: expect.stringMatching(/:dm_member:0$/),
        })
        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(true)
        expect(response.logs.map((log) => log.message)).toContain('The message was sent.')
    })

    it('fails the step with the reason Django gives', async () => {
        tester.mockInternalFetchResponse({
            status: 422,
            body: { detail: "The recipient 'x@example.com' is not a member of this project." },
        })

        let response = await tester.invoke(INPUTS, undefined, WORKFLOW_STEP)
        response = await tester.resumeInvocation(response.invocation)

        expect(response.error).toEqual(
            "Could not message the team member on Slack (422): The recipient 'x@example.com' is not a member of this project."
        )
    })
})
