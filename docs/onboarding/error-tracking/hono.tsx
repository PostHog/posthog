import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getNodeJSSteps as getNodeJSStepsPA } from '../product-analytics/nodejs'
import { StepDefinition } from '../steps'

export const getHonoSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    const installSteps = getNodeJSStepsPA(ctx)

    const exceptionHandlingStep: StepDefinition = {
        title: 'Exception handling example',
        badge: 'required',
        content: (
            <>
                <Markdown>
                    {dedent`
                        Hono uses [\`app.onError\`](https://hono.dev/docs/api/exception#handling-httpexception) to handle uncaught exceptions. You can take advantage of this for error tracking. 
                        
                        Remember to **export** your [project API key](https://app.posthog.com/settings/project#variables) as an environment variable.
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'typescript',
                            file: 'index.ts',
                            code: dedent`
                              import { PostHog } from 'posthog-node'
                              const posthog = new PostHog(process.env.POSTHOG_PUBLIC_KEY, { host: 'https://us.i.posthog.com' })
                              app.onError(async (err, c) => {
                                posthog.captureException(err, 'user_distinct_id_with_err_rethrow', {
                                  path: c.req.path,
                                  method: c.req.method,
                                  url: c.req.url,
                                  headers: c.req.header(),
                                  // ... other properties
                                })
                                await posthog.flush()
                                // other error handling logic
                                return c.text('Internal Server Error', 500)
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
                    Before proceeding, let's make sure exception events are being captured and sent to PostHog. You should see events appear in the activity feed.

                    [Check for exceptions in PostHog](https://app.posthog.com/activity/explore)
                `}
            </Markdown>
        ),
    }

    return [
        ...installSteps,
        exceptionHandlingStep,
        verifyStep,
    ]
}

export const HonoInstallation = createInstallation(getHonoSteps)
