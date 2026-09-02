import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'
import { DEFAULT_SNIPPET_METHODS, snippetFunctions } from './_snippets/js-snippet-builder'
import { SDK_DEFAULTS_DATE } from './_snippets/sdkDefaults'

export const getBubbleInstallSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    return [
        {
            title: 'Copy the web snippet',
            badge: 'required',
            content: (
                <>
                    <Markdown>First, copy your PostHog web snippet:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'html',
                                file: 'HTML',
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
            title: 'Add to Bubble',
            badge: 'required',
            content: (
                <Markdown>
                    {dedent`
                        Go to your Bubble site settings by clicking on the icon in the left-hand menu. If you haven't
                        already, sign up for at least the **Starter** site plan. This enables you to add custom code. Then:

                        1. Go to the **SEO / metatags** tab in site settings.
                        2. Paste your PostHog snippet in the **Script/meta tags in header** section.
                        3. Deploy your site to live.
                    `}
                </Markdown>
            ),
        },
    ]
}

export const getBubbleEventStep = (ctx: OnboardingComponentsContext): StepDefinition => {
    const { snippets } = ctx

    const JSEventCapture = snippets?.JSEventCapture

    return {
        title: 'Send events',
        content: <>{JSEventCapture && <JSEventCapture />}</>,
    }
}

export const getBubbleSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => [
    ...getBubbleInstallSteps(ctx),
    getBubbleEventStep(ctx),
]

export const BubbleInstallation = createInstallation(getBubbleSteps)
