import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'
import { DEFAULT_SNIPPET_METHODS, snippetFunctions } from './_snippets/js-snippet-builder'
import { SDK_DEFAULTS_DATE } from './_snippets/sdkDefaults'

export const getWebflowInstallSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
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
            title: 'Add to Webflow',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Go to your Webflow site settings by clicking on the menu icon in the top left. If you haven't
                        already, sign up for at least the **Basic** site plan. This enables you to add custom code.
                        Then:
                    </Markdown>
                    <Markdown>
                        {`1. Go to the **Custom code** tab in site settings.
2. In the **Head code** section, paste your PostHog snippet and press save.
3. Publish your site.`}
                    </Markdown>
                </>
            ),
        },
    ]
}

export const getWebflowEventStep = (ctx: OnboardingComponentsContext): StepDefinition => {
    const { snippets } = ctx

    const JSEventCapture = snippets?.JSEventCapture

    return {
        title: 'Send events',
        content: <>{JSEventCapture && <JSEventCapture />}</>,
    }
}

export const getWebflowSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => [
    ...getWebflowInstallSteps(ctx),
    getWebflowEventStep(ctx),
]

export const WebflowInstallation = createInstallation(getWebflowSteps)
