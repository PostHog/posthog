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

    const appFrame = (name: string): Record<string, any> => ({
        source: `src/${name}.ts`,
        line: 1,
        resolved_name: name,
        resolved: true,
        in_app: true,
    })
    const minifiedFrame = { source: 'main.3f9a.js', line: 1, mangled_name: 't.e', resolved: false, in_app: true }

    it.each<[string, Record<string, any>, string, string]>([
        [
            'adds the context lines and the resolved in-app frames, crash site first, with no secrets',
            {
                $exception_types: ['RangeError'],
                $exception_values: ['Invalid Date\nvalue: `abc` @octocat [link](https://evil.example)'],
                $exception_list: [
                    {
                        stacktrace: {
                            frames: [
                                {
                                    source: 'node_modules/react-dom.js',
                                    line: 10,
                                    resolved_name: 'commit',
                                    resolved: true,
                                    in_app: false,
                                },
                                {
                                    source: 'https://user:password@example.com',
                                    line: 2,
                                    resolved_name: 'alice@example.com',
                                    resolved: true,
                                    in_app: true,
                                },
                                {
                                    source: 'https://example.com/reset-password/3f2b8c1e-9d4a-4e7b-8a6c-0d1e2f3a4b5c',
                                    line: 1,
                                    column: 20,
                                    resolved_name: 'onSubmit',
                                    resolved: true,
                                    in_app: true,
                                },
                                {
                                    source: '/home/bob/app.py',
                                    line: 7,
                                    resolved_name: 'handler_EXAMPLE0123456789',
                                    resolved: true,
                                    in_app: true,
                                },
                                {
                                    source: '/Users/alice/projects/shop/src/resetPasswordToken_ABCDEF0123456789abcdef0123456789.ts',
                                    line: 3,
                                    resolved_name: 'handleCheckoutSubmitButtonClickEvent',
                                    resolved: true,
                                    in_app: true,
                                    code_variables: { password: 'hunter2' },
                                    context: { line: { number: 3, line: 'const apiKey = "sk_live_example"' } },
                                },
                                minifiedFrame,
                                {
                                    source: 'https://app.example.com/static/js/src/checkout.ts?token=secret#frag',
                                    line: 42,
                                    resolved_name: 'parse`Date`',
                                    resolved: true,
                                    in_app: true,
                                },
                            ],
                        },
                    },
                ],
                $current_url: 'https://example.com/reset?token=secret#access_token=abc',
                $browser: 'Chrome',
                $browser_version: 129,
                $os: 'Mac OS X',
                $os_version: '10.15.7\n\n[link](https://evil.example)',
                $exception_release: { version: '1.4.2' },
                $session_id: 'session/1',
                $recording_status: 'active',
            },
            'RangeError: Invalid Date value: `abc` @octocat [link](https://evil.example)',
            '```\nInvalid Date\nvalue: \'abc\' @octocat [link](https://evil.example)\n```\n\n- Browser: `Chrome 129`\n- OS: `Mac OS X 10.15.7  [link](https://evil.example)`\n- Release: `1.4.2`\n- Session replay: https://us.posthog.com/projects/1/replay/session%2F1\n\n```\n  File "checkout.ts", line: 42, in: [redacted]\n  File "[redacted]", line: 3, in: handleCheckoutSubmitButtonClickEvent\n  File "app.py", line: 7, in: [redacted]\n  File "[redacted]", line: 1, in: onSubmit\n  File "[redacted]", line: 2, in: [redacted]\n```',
        ],
        [
            'leaves out missing lines, replay when recording was off, and a trace with no resolved frame',
            {
                $exception_types: ['RangeError'],
                $exception_values: [''],
                $exception_list: [{ stacktrace: { frames: [minifiedFrame] } }],
                $browser: 'Chrome',
                $session_id: 'session-1',
                $recording_status: 'disabled',
            },
            'RangeError',
            '\n\n- Browser: `Chrome`',
        ],
        [
            'shows at most 5 frames',
            {
                $exception_types: ['RangeError'],
                $exception_values: ['Invalid Date'],
                $exception_list: [{ stacktrace: { frames: ['a', 'b', 'c', 'd', 'e', 'f', 'g'].map(appFrame) } }],
            },
            'RangeError: Invalid Date',
            '```\nInvalid Date\n```\n\n\n```\n  File "g.ts", line: 1, in: g\n  File "f.ts", line: 1, in: f\n  File "e.ts", line: 1, in: e\n  File "d.ts", line: 1, in: d\n  File "c.ts", line: 1, in: c\n```',
        ],
        [
            'reads only the last 50 frames of a deep stack',
            {
                $exception_types: ['RangeError'],
                $exception_values: ['Invalid Date'],
                $exception_list: [{ stacktrace: { frames: [appFrame('a'), ...Array(50).fill(minifiedFrame)] } }],
            },
            'RangeError: Invalid Date',
            '```\nInvalid Date\n```\n',
        ],
        [
            'leaves out the trace of a stack over 2000 frames',
            {
                $exception_types: ['RangeError'],
                $exception_values: ['Invalid Date'],
                $exception_list: [{ stacktrace: { frames: [...Array(2000).fill(minifiedFrame), appFrame('a')] } }],
            },
            'RangeError: Invalid Date',
            '```\nInvalid Date\n```\n',
        ],
    ])('%s', async (_name, properties, expectedTitle, expectedDescription) => {
        const { title: _title, description: _description, ...inputs } = baseInputs
        const response = await tester.invoke(inputs, { event: { properties } })

        expect(response.error).toBeUndefined()
        const body = parseJSON((response.invocation.queueParameters as any).body)
        expect(body.title).toEqual(expectedTitle)
        for (const secret of [
            'token=',
            'access_token',
            'alice',
            'bob',
            'EXAMPLE0123',
            'hunter2',
            'sk_live',
            'password@',
            '3f2b8c1e',
            'ABCDEF0123',
        ]) {
            expect(JSON.stringify(body)).not.toContain(secret)
        }
        expect(body.body).toEqual(
            `${expectedDescription}\n\n[View in PostHog](https://us.posthog.com/projects/1/error-tracking/issue-uuid)`
        )
    })
})
