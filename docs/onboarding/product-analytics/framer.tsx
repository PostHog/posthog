import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'
import { DEFAULT_SNIPPET_METHODS, snippetFunctions } from './_snippets/js-snippet-builder'
import { SDK_DEFAULTS_DATE } from './_snippets/sdkDefaults'

export const getFramerInstallSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
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
            title: 'Add to Framer',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Go to your Framer project settings by clicking the gear in the top right. If you haven't
                        already, sign up for at least the **Mini** site plan. This enables you to add custom code. Then:
                    </Markdown>
                    <Markdown>
                        {`1. Go to the **General** tab in site settings.
2. Scroll down to the **Custom Code** section.
3. Under **End of <head> tag**, paste your PostHog snippet.
4. Press save, and then publish your site.`}
                    </Markdown>
                </>
            ),
        },
    ]
}

export const getFramerEventStep = (ctx: OnboardingComponentsContext): StepDefinition => {
    const { snippets } = ctx

    const JSEventCapture = snippets?.JSEventCapture

    return {
        title: 'Send events',
        content: <>{JSEventCapture && <JSEventCapture />}</>,
    }
}

export const getFramerSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => [
    ...getFramerInstallSteps(ctx),
    getFramerEventStep(ctx),
]

export const FramerInstallation = createInstallation(getFramerSteps)
