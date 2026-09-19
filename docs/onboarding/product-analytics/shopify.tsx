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

export const getShopifyPerformanceStep = (ctx: OnboardingComponentsContext): StepDefinition => {
    const { CodeBlock, Markdown, dedent } = ctx

    return {
        title: 'Tune for performance',
        badge: 'optional',
        content: (
            <>
                <Markdown>
                    The snippet loads PostHog asynchronously from a separate assets host, so it does not block your
                    store from rendering. To reduce the work PostHog does on each page, add these options to the
                    `posthog.init` call you just pasted. Each option removes a feature, so set only the ones you can do
                    without.
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'javascript',
                            file: 'theme.liquid',
                            code: dedent`
                            posthog.init('<ph_project_token>', {
                                api_host: '<ph_client_api_host>',
                                defaults: '${SDK_DEFAULTS_DATE}',
                                autocapture: false, // no click or form capture
                                capture_heatmaps: false, // no heatmap data
                                disable_session_recording: true, // no session replay script
                                disable_surveys: true, // no surveys script
                                capture_performance: false, // no web vitals or network timing
                                advanced_disable_flags: true, // no /flags request
                            })
                        `,
                        },
                    ]}
                />
                <Markdown>
                    Leave out `advanced_disable_flags` if you use feature flags, experiments, or surveys, because they
                    all need that request. If you turn off autocapture, add
                    [`posthog.capture()`](https://posthog.com/docs/product-analytics/capture-events) calls for the
                    actions you still want to measure. See the [JavaScript config
                    reference](https://posthog.com/docs/libraries/js/config) for the full list of options.
                </Markdown>
            </>
        ),
    }
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
    getShopifyPerformanceStep(ctx),
    getShopifyEventStep(ctx),
]

export const ShopifyInstallation = createInstallation(getShopifySteps)
