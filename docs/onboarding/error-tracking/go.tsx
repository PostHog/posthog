import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getGoSteps as getGoStepsPA } from '../product-analytics/go'
import { StepDefinition } from '../steps'

export const getGoSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    const installSteps = getGoStepsPA(ctx)

    const captureStep: StepDefinition = {
        title: 'Capture errors',
        badge: 'required',
        content: (
            <>
                <Markdown>
                    {dedent`
                        Use \`NewDefaultException\` when you have an error value and want PostHog to group it in Error tracking.
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'go',
                            file: 'Go',
                            code: dedent`
                                import (
                                    "time"

                                    "github.com/posthog/posthog-go"
                                )

                                if err != nil {
                                    client.Enqueue(posthog.NewDefaultException(
                                        time.Now(),
                                        "user_distinct_id",
                                        "RuntimeError",
                                        err.Error(),
                                    ))
                                }
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        If you want to attach custom properties, enqueue a \`posthog.Exception\` instead.
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'go',
                            file: 'Go',
                            code: dedent`
                                client.Enqueue(posthog.Exception{
                                    DistinctId: "user_distinct_id",
                                    Timestamp:  time.Now(),
                                    Properties: posthog.Properties{
                                        "route": "/checkout",
                                    },
                                    ExceptionList: []posthog.ExceptionItem{
                                        {Type: "RuntimeError", Value: err.Error()},
                                    },
                                })
                            `,
                        },
                    ]}
                />
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

    return [...installSteps, captureStep, verifyStep]
}

export const GoInstallation = createInstallation(getGoSteps)
