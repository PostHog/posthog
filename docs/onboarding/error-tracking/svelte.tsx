import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getSvelteSteps as getSvelteStepsPA } from '../product-analytics/svelte'
import { StepDefinition } from '../steps'

export const getSvelteSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    const installSteps = getSvelteStepsPA(ctx)

    const clientExceptionCaptureStep: StepDefinition = {
        title: 'Set up client-side exception capture',
        badge: 'required',
        content: (
            <>
                <Markdown>
                    {dedent`
                        [SvelteKit Hooks](https://svelte.dev/docs/kit/hooks) can be used to capture exceptions in the client and server-side.

                        Capture exceptions in the \`handleError\` callback in your client-side hooks file:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'javascript',
                            file: 'src/hooks.client.js',
                            code: dedent`
                              import posthog from 'posthog-js';
                              import type { HandleClientError } from '@sveltejs/kit';
                              export const handleError = ({ error, status }: HandleClientError) => {
                                // SvelteKit 2.0 offers a reliable way to check for a 404 error:
                                if (status !== 404) {
                                    posthog.captureException(error);
                                }
                              };
                            `,
                        },
                    ]}
                />
            </>
        ),
    }

    const serverExceptionCaptureStep: StepDefinition = {
        title: 'Set up server-side exception capture',
        badge: 'required',
        content: (
            <>
                <Markdown>
                    {dedent`
                        To capture exceptions on the server-side, you will also need to implement the \`handleError\` callback:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'javascript',
                            file: 'src/hooks.server.ts',
                            code: dedent`
                              import type { HandleServerError } from '@sveltejs/kit';
                              import { PostHog } from 'posthog-node';
                              const client = new PostHog(
                                '<ph_project_api_key>',
                                { host: 'https://us.i.posthog.com' }
                              )
                              export const handleError = async ({ error, status }: HandleServerError) => {
                                if (status !== 404) {
                                    client.captureException(error);
                                    await client.shutdown();
                                }
                              };
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
        clientExceptionCaptureStep,
        serverExceptionCaptureStep,
        verifyStep,
    ]
}

export const SvelteInstallation = createInstallation(getSvelteSteps)
