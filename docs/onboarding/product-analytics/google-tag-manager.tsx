import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'
import { DEFAULT_SNIPPET_METHODS, snippetFunctions } from './_snippets/js-snippet-builder'
import { SDK_DEFAULTS_DATE } from './_snippets/sdkDefaults'

export const getGoogleTagManagerInstallSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    return [
        {
            title: 'Create a custom HTML tag',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Google Tag Manager (GTM) lets you manage tracking scripts without code changes. You can add
                        PostHog to your site using a custom HTML tag.
                    </Markdown>
                    <Markdown>
                        {`1. Log into your Google Tag Manager account and open your container.
2. Click **Tags** > **New** > **Tag Configuration** > **Custom HTML**.
3. Paste the following code:`}
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'html',
                                file: 'Custom HTML Tag',
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
            title: 'Configure the trigger',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {`1. Under **Triggering**, select **All Pages** to load PostHog on every page.
2. Save the tag, then click **Submit** to publish your changes.`}
                    </Markdown>
                    <Markdown>
                        Once published, PostHog will automatically capture pageviews, clicks, and other events on your
                        site.
                    </Markdown>
                </>
            ),
        },
    ]
}

export const getGoogleTagManagerEventStep = (ctx: OnboardingComponentsContext): StepDefinition => {
    const { snippets } = ctx

    const JSEventCapture = snippets?.JSEventCapture

    return {
        title: 'Send events',
        content: <>{JSEventCapture && <JSEventCapture />}</>,
    }
}

export const getGoogleTagManagerSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => [
    ...getGoogleTagManagerInstallSteps(ctx),
    getGoogleTagManagerEventStep(ctx),
]

export const GoogleTagManagerInstallation = createInstallation(getGoogleTagManagerSteps)
