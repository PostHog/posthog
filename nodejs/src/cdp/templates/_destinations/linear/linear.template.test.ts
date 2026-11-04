import { parseJSON } from '../../../../common/utils/json-parse'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './linear.template'

describe('linear template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
    })

    const baseInputs = {
        linear_workspace: { access_token: 'token' },
        team: 'linear-team-id',
        title: 'TypeError',
        description: 'Something broke',
        posthog_issue_id: 'issue-uuid',
    }

    it.each<[string, string | undefined, string]>([
        [
            'attaches the fingerprint URL when posthog_issue_url is provided',
            'https://us.posthog.com/project/1/error_tracking/fingerprint/fp%2F1',
            'https://us.posthog.com/project/1/error_tracking/fingerprint/fp%2F1',
        ],
        [
            'falls back to the issue-id URL for functions without posthog_issue_url',
            undefined,
            '/error-tracking/issue-uuid',
        ],
    ])('%s', async (_name, posthogIssueUrl, expectedLinkPart) => {
        const createResponse = await tester.invoke({ ...baseInputs, posthog_issue_url: posthogIssueUrl })
        expect(createResponse.error).toBeUndefined()

        const attachmentResponse = await tester.invokeFetchResponse(createResponse.invocation, {
            status: 200,
            body: { data: { issueCreate: { success: true, issue: { identifier: 'LIN-1' } } } },
        })

        expect(attachmentResponse.error).toBeUndefined()
        const attachmentBody = (attachmentResponse.invocation.queueParameters as any).body
        expect(attachmentBody).toContain('attachmentCreate')
        expect(attachmentBody).toContain(expectedLinkPart)
    })

    it('builds the title and description from the event properties, with the stack trace', async () => {
        const { title: _title, description: _description, ...inputs } = baseInputs
        const response = await tester.invoke(inputs, {
            event: {
                properties: {
                    $exception_types: ['RangeError'],
                    $exception_values: ['Invalid Date'],
                    $current_url: 'https://example.com/reset?token=secret',
                    $session_id: 'session-1',
                    $exception_list: [
                        {
                            stacktrace: {
                                frames: [
                                    {
                                        source: 'src/checkout.ts',
                                        line: 42,
                                        resolved_name: 'parseDate',
                                        resolved: true,
                                        in_app: true,
                                    },
                                ],
                            },
                        },
                    ],
                },
            },
        })

        expect(response.error).toBeUndefined()
        const mutation = parseJSON((response.invocation.queueParameters as any).body).query
        expect(mutation).toContain('title: "RangeError: Invalid Date"')
        expect(mutation).not.toContain('token=secret')
        expect(mutation).toContain(
            'description: "```\\nInvalid Date\\n```\\n\\n- Session replay: https://us.posthog.com/projects/1/replay/session-1\\n\\n```\\n  File \\"checkout.ts\\", line: 42, in: parseDate\\n```"'
        )
    })
})
