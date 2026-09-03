import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'
import { DEFAULT_SNIPPET_METHODS, snippetFunctions } from './_snippets/js-snippet-builder'
import { SDK_DEFAULTS_DATE } from './_snippets/sdkDefaults'

export const getShopifyInstallSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    return [
        {
            title: 'Open theme editor',
            badge: 'required',
            content: (
                <Markdown>
                    In your Shopify admin, go to **Online Store** &gt; **Themes**. Click **Actions** &gt; **Edit code**
                    on your current theme.
                </Markdown>
            ),
        },
        {
            title: 'Add the PostHog snippet',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Open `theme.liquid` and paste the following code just before the closing `&lt;/head&gt;` tag:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'html',
                                file: 'theme.liquid',
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
                    <Markdown>Click **Save**.</Markdown>
                </>
            ),
        },
    ]
}

export const getShopifyEventStep = (ctx: OnboardingComponentsContext): StepDefinition => {
    const { Markdown } = ctx

    return {
        title: 'Verify installation',
        badge: 'recommended',
        content: (
            <Markdown>
                PostHog will now capture pageviews, clicks, and other events on your Shopify store. See the [Shopify
                integration docs](https://posthog.com/docs/libraries/shopify) for tracking checkout events and revenue.
            </Markdown>
        ),
    }
}

export const getShopifySteps = (ctx: OnboardingComponentsContext): StepDefinition[] => [
    ...getShopifyInstallSteps(ctx),
    getShopifyEventStep(ctx),
]

export const ShopifyInstallation = createInstallation(getShopifySteps)
