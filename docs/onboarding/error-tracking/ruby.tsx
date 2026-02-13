import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getRubySteps as getRubyStepsPA } from '../product-analytics/ruby'
import { StepDefinition } from '../steps'

export const getRubySteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, Blockquote, dedent } = ctx

    const installSteps = getRubyStepsPA(ctx)

    const manualCaptureStep: StepDefinition = {
        title: 'Manually capture exceptions',
        badge: 'required',
        content: (
            <>
                <Blockquote>
                    <Markdown>
                        {dedent`
                            **Using Ruby on Rails?** The \`posthog-rails\` gem provides automatic exception capture for controllers and background jobs. Select "Ruby on Rails" from the SDK list for setup instructions.
                        `}
                    </Markdown>
                </Blockquote>
                <Markdown>
                    {dedent`
                        To capture exceptions in your Ruby application, use the \`capture_exception\` method:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'ruby',
                            file: 'Ruby',
                            code: dedent`
                                begin
                                  # Code that might raise an exception
                                  raise StandardError, "Something went wrong"
                                rescue => e
                                  posthog.capture_exception(
                                    e,
                                    distinct_id: 'user_distinct_id',
                                    properties: {
                                      custom_property: 'custom_value'
                                    }
                                  )
                                end
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        The \`capture_exception\` method accepts the following parameters:

                        | Param | Type | Description |
                        | --- | --- | --- |
                        | \`exception\` | \`Exception\` | The exception object to capture (required) |
                        | \`distinct_id\` | \`String\` | The distinct ID of the user (optional) |
                        | \`properties\` | \`Hash\` | Additional properties to attach to the exception event (optional) |
                    `}
                </Markdown>
            </>
        ),
    }

    const verifyStep: StepDefinition = {
        title: 'Verify error tracking',
        badge: 'recommended',
        checkpoint: true,
        content: (
            <Markdown>
                {dedent`
                    Confirm exception events are being captured and sent to PostHog. You should see events appear in the activity feed.

                    [Check for exceptions in PostHog](https://app.posthog.com/activity/explore)
                `}
            </Markdown>
        ),
    }

    return [...installSteps, manualCaptureStep, verifyStep]
}

export const RubyInstallation = createInstallation(getRubySteps)
