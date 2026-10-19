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
            '/error-tracking/issue-uuid',
        ],
    ])('%s', async (_name, posthogIssueUrl, expectedLinkPart) => {
        const response = await tester.invoke({ ...baseInputs, posthog_issue_url: posthogIssueUrl })

        expect(response.error).toBeUndefined()
        const body = parseJSON((response.invocation.queueParameters as any).body)
        expect(body.body).toContain(`[View in PostHog](`)
        expect(body.body).toContain(expectedLinkPart)
    })

    it.each<[string, Record<string, any>, string, string]>([
        [
            'adds a line for each context property on the event',
            {
                $exception_types: ['RangeError'],
                $exception_values: ['Invalid Date'],
                $current_url: 'https://example.com/checkout',
                $browser: 'Chrome',
                $browser_version: 129,
                $os: 'Mac OS X',
                $os_version: '10.15.7',
                $exception_release: { version: '1.4.2' },
                $session_id: 'session/1',
                $recording_status: 'active',
            },
            'RangeError: Invalid Date',
            'Invalid Date\n\n- URL: https://example.com/checkout\n- Browser: Chrome 129\n- OS: Mac OS X 10.15.7\n- Release: 1.4.2\n- Session replay: https://us.posthog.com/projects/1/replay/session%2F1',
        ],
        [
            'leaves out lines whose property is missing, and replay when recording was off',
            {
                $exception_types: ['RangeError'],
                $exception_values: [''],
                $browser: 'Chrome',
                $session_id: 'session-1',
                $recording_status: 'disabled',
            },
            'RangeError',
            '\n\n- Browser: Chrome',
        ],
    ])('%s', async (_name, properties, expectedTitle, expectedDescription) => {
        const { title: _title, description: _description, ...inputs } = baseInputs
        const response = await tester.invoke(inputs, { event: { properties } })

        expect(response.error).toBeUndefined()
        const body = parseJSON((response.invocation.queueParameters as any).body)
        expect(body.title).toEqual(expectedTitle)
        expect(body.body).toEqual(
            `${expectedDescription}\n\n[View in PostHog](https://us.posthog.com/projects/1/error-tracking/issue-uuid)`
        )
    })
})
