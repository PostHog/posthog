import { TemplateTester } from '../../test/test-helpers'
import { template } from './linear.template'

describe('linear template', () => {
    const tester = new TemplateTester(template)

    const commonInputs = {
        linear_workspace: { access_token: 'test-access-token' },
        team: 'test-team-id',
        title: 'TypeError',
        description: 'undefined is not a function',
        posthog_issue_id: 'issue-abc',
    }

    beforeEach(async () => {
        await tester.beforeEach()
    })

    it('does not create a Linear issue when one already exists for the PostHog issue', async () => {
        const response = await tester.invoke(commonInputs)

        // First call is the dedup lookup against Linear, keyed on the PostHog issue URL.
        expect(response.invocation.queueParameters?.body).toContain('attachmentsForURL')
        expect(response.invocation.queueParameters?.body).toContain(
            'https://us.posthog.com/projects/1/error_tracking/issue-abc'
        )

        const lookupResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { data: { attachmentsForURL: { nodes: [{ id: 'existing-attachment' }] } } },
        })

        // A matching attachment means we already created a Linear issue, so we stop here.
        expect(lookupResponse.error).toBeUndefined()
        expect(lookupResponse.finished).toBe(true)
        expect(lookupResponse.invocation.queueParameters).toBeUndefined()
        expect(lookupResponse.logs.map((l) => l.message)).toContain(
            'A Linear issue already exists for PostHog issue issue-abc, skipping creation.'
        )
    })

    it('creates the issue and links it back when none exists yet', async () => {
        const response = await tester.invoke(commonInputs)

        const lookupResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { data: { attachmentsForURL: { nodes: [] } } },
        })

        // No existing attachment, so we create the issue.
        expect(lookupResponse.invocation.queueParameters?.body).toContain('issueCreate')
        expect(lookupResponse.invocation.queueParameters?.body).toContain('test-team-id')

        const issueResponse = await tester.invokeFetchResponse(lookupResponse.invocation, {
            status: 200,
            body: { data: { issueCreate: { success: true, issue: { identifier: 'ENG-1' } } } },
        })

        // Then we attach the PostHog issue link, tagged with the originating project name.
        expect(issueResponse.invocation.queueParameters?.body).toContain('attachmentCreate')
        expect(issueResponse.invocation.queueParameters?.body).toContain('PostHog issue (project-name)')
        expect(issueResponse.invocation.queueParameters?.body).toContain(
            'https://us.posthog.com/projects/1/error_tracking/issue-abc'
        )

        const attachmentResponse = await tester.invokeFetchResponse(issueResponse.invocation, {
            status: 200,
            body: { data: { attachmentCreate: { success: true } } },
        })

        expect(attachmentResponse.error).toBeUndefined()
        expect(attachmentResponse.finished).toBe(true)
    })
})
