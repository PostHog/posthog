import { parseJSON } from '../../../../common/utils/json-parse'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './github.template'

describe('github template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
    })

    const baseInputs = {
        github_installation: { access_token: 'token', account: { name: 'PostHog' } },
        repository: 'posthog',
        title: 'TypeError',
        description: 'Something broke',
        posthog_issue_id: 'issue-uuid',
    }

    it.each<[string, string | undefined, string]>([
        [
            'links via the fingerprint URL when posthog_issue_url is provided',
            'https://us.posthog.com/project/1/error_tracking/fingerprint/fp%2F1',
            'https://us.posthog.com/project/1/error_tracking/fingerprint/fp%2F1',
        ],
        [
            'falls back to the issue-id URL for functions without posthog_issue_url',
            undefined,
            '/error_tracking/issue-uuid',
        ],
    ])('%s', async (_name, posthogIssueUrl, expectedLinkPart) => {
        const response = await tester.invoke({ ...baseInputs, posthog_issue_url: posthogIssueUrl })

        expect(response.error).toBeUndefined()
        const body = parseJSON((response.invocation.queueParameters as any).body)
        expect(body.body).toContain(`[View in PostHog](`)
        expect(body.body).toContain(expectedLinkPart)
    })
})
