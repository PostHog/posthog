import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const OnFeatureFlagsCallbackSnippet = (): JSX.Element => {
    const { CodeBlock, dedent, Markdown } = useMDXComponents()

    return (
        <>
            <Markdown>
                {dedent`
                    Every time a user loads a page, we send a request in the background to fetch the feature flags that apply to that user. We store those flags in your chosen persistence option (local storage by default).

                    This means that for most pages, the feature flags are available immediately — **except for the first time a user visits**.

                    To handle this, you can use the \`onFeatureFlags\` callback to wait for the feature flag request to finish:
                `}
            </Markdown>
            <CodeBlock
                language="javascript"
                code={dedent`
                    posthog.onFeatureFlags(function (flags, flagVariants, { errorsLoading }) {
                        // feature flags are guaranteed to be available at this point
                        if (posthog.isFeatureEnabled('flag-key')) {
                            // do something
                        }
                    })
                `}
            />
        </>
    )
}


