import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const SurveysFinalSteps = (): JSX.Element => {
    const { Markdown, dedent } = useMDXComponents()

    return (
        <Markdown>
            {dedent`
                After installing the PostHog SDK, you can create your first survey.


                | Resource | Description |
                |----------|-------------|
                | [Creating surveys](https://posthog.com/docs/surveys/creating-surveys) | Learn how to build and customize your surveys |
                | [Targeting surveys](https://posthog.com/docs/surveys/targeting) | Show surveys to specific users based on properties, events, or feature flags |
                | [How to create custom surveys](https://posthog.com/tutorials/survey) | Build advanced survey experiences with custom code |
                | [Framework guides](https://posthog.com/docs/surveys/tutorials#framework-guides) | Setup guides for React, Next.js, Vue, and other frameworks |
                | [More tutorials](https://posthog.com/docs/surveys/tutorials) | Other real-world examples and use cases |

                You should also [identify](https://posthog.com/docs/product-analytics/identify) users and [capture events](https://posthog.com/docs/product-analytics/capture-events) with PostHog to control who and when to show surveys to your users.

                Not all survey features are available on every SDK. See the [SDK feature support matrix](https://posthog.com/docs/surveys/sdk-feature-support) for a full comparison.
            `}
        </Markdown>
    )
}
