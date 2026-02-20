import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getNodeJSSteps as getNodeJSStepsPA } from '../product-analytics/nodejs'
import { StepDefinition } from '../steps'

export const getNodeJSSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, Blockquote, dedent } = ctx

    const installSteps = getNodeJSStepsPA(ctx)

    const exceptionAutocaptureStep: StepDefinition = {
        title: 'Configure exception autocapture',
        badge: 'recommended',
        content: (
            <>
                <Markdown>
                    {dedent`
                        You can enable exception autocapture when initializing the PostHog client to automatically capture uncaught exceptions and unhandled rejections in your Node app.
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'javascript',
                            file: 'Node.js',
                            code: dedent`
                                import { PostHog } from 'posthog-node'
                                const client = new PostHog(
                                    '<ph_project_api_key>',
                                    { host: 'https://us.i.posthog.com', enableExceptionAutocapture: true }
                                )
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        If you are using the Express framework, you will need to import and call \`setupExpressErrorHandler\` with your PostHog client and Express app. This is because Express handles uncaught exceptions internally meaning exception autocapture will not work by default.
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'javascript',
                            file: 'server.ts',
                            code: dedent`
                                import express from 'express'
                                import { PostHog, setupExpressErrorHandler } from 'posthog-node'
                                const app = express()
                                const posthog = new PostHog(PH_API_KEY)
                                setupExpressErrorHandler(posthog, app)
                            `,
                        },
                    ]}
                />
                <Blockquote>
                    <Markdown>
                        {dedent`
                            **Note:** Error tracking requires access the file system to process stack traces. Some providers, like Cloudflare Workers, do not support Node.js runtime APIs by default and need to be [included as per their documentation](https://developers.cloudflare.com/workers/runtime-apis/nodejs/#nodejs-compatibility).
                        `}
                    </Markdown>
                </Blockquote>
            </>
        ),
    }

    const manualCaptureStep: StepDefinition = {
        title: 'Manually capture exceptions',
        badge: 'optional',
        content: (
            <>
                <Markdown>
                    {dedent`
                        If you need to manually capture exceptions, you can do so by calling the \`captureException\` method:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'javascript',
                            file: 'Node.js',
                            code: dedent`
                                posthog.captureException(e, 'user_distinct_id', additionalProperties)
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        This is helpful if you've built your own error handling logic or want to capture exceptions normally handled by the framework.
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

    return [
        ...installSteps,
        exceptionAutocaptureStep,
        manualCaptureStep,
        verifyStep,
    ]
}

export const NodeJSInstallation = createInstallation(getNodeJSSteps)
