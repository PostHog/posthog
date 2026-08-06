import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'
import { DEFAULT_SNIPPET_METHODS, snippetFunctions } from './_snippets/js-snippet-builder'
import { SDK_DEFAULTS_DATE } from './_snippets/sdkDefaults'

export const getRetoolSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, CalloutBox, dedent } = ctx

    return [
        {
            title: 'Open custom scripts',
            badge: 'required',
            content: (
                <Markdown>
                    Retool is a platform for building internal tools. In your Retool app, go to **Settings** &gt;
                    **Custom Scripts**.
                </Markdown>
            ),
        },
        {
            title: 'Add the PostHog snippet',
            badge: 'required',
            content: (
                <>
                    <Markdown>Add the following code to the **Head** section:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'html',
                                file: 'Head section',
                                code: dedent`
                                <script>
                                    ${snippetFunctions(DEFAULT_SNIPPET_METHODS)}
                                    posthog.init('<ph_project_token>', {
                                        api_host: '<ph_client_api_host>',
                                        defaults: '${SDK_DEFAULTS_DATE}'
                                    })
                                </script>
                            `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Verify installation',
            badge: 'recommended',
            content: (
                <>
                    <Markdown>
                        Save and refresh your app. PostHog will now automatically capture pageviews, clicks, and other
                        events as your app is used.
                    </Markdown>
                    <CalloutBox type="fyi" title="Learn more">
                        <Markdown>
                            See the [Retool integration docs](https://posthog.com/docs/libraries/retool) for more
                            details.
                        </Markdown>
                    </CalloutBox>
                </>
            ),
        },
    ]
}

export const RetoolInstallation = createInstallation(getRetoolSteps)
