import { parseJSON } from '../../../../common/utils/json-parse'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './gitlab.template'

describe('gitlab template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
    })

    it('puts the title in a code span and adds the stack trace and the PostHog link after the description', async () => {
        const response = await tester.invoke(
            {
                gitlab_project: { access_token: 'token', hostname: 'https://gitlab.com', project_id: 1 },
                posthog_issue_id: 'issue-uuid',
            },
            {
                event: {
                    properties: {
                        $exception_types: ['RangeError'],
                        $exception_values: ['Invalid `Date` @admin https://example.com'],
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
            }
        )

        expect(response.error).toBeUndefined()
        const body = parseJSON((response.invocation.queueParameters as any).body)
        expect(body.title).toEqual("`RangeError: Invalid 'Date' @admin https://example.com`")
        expect(body.description).toEqual(
            '```\nInvalid \'Date\' @admin https://example.com\n```\n\n\n```\n  File "checkout.ts", line: 42, in: parseDate\n```\n\n[View in PostHog](https://us.posthog.com/projects/1/error-tracking/issue-uuid)'
        )
    })
})
