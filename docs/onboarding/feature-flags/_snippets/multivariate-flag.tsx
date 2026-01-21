import { memo } from 'react'
import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const MultivariateFlagSnippet = memo(function MultivariateFlagSnippet({ language = 'javascript' }: { language?: string }): JSX.Element {
    const { CodeBlock, dedent } = useMDXComponents()

    const snippets: Record<string, string> = {
        javascript: dedent`
            if (posthog.getFeatureFlag('flag-key') == 'variant-key') { // replace 'variant-key' with the key of your variant
                // Do something differently for this user
                // Optional: fetch the payload
                const matchedFlagPayload = posthog.getFeatureFlagPayload('flag-key')
            }
        `,
        react: dedent`
            import { useFeatureFlagVariantKey } from '@posthog/react'

            function App() {
                const variantKey = useFeatureFlagVariantKey('show-welcome-message')
                let welcomeMessage = ''
                if (variantKey === 'variant-a') {
                    welcomeMessage = 'Welcome to the Alpha!'
                } else if (variantKey === 'variant-b') {
                    welcomeMessage = 'Welcome to the Beta!'
                }
                return (
                    <div className="App">
                        {welcomeMessage ? (
                            <div>
                                <h1>{welcomeMessage}</h1>
                                <p>Thanks for trying out our feature flags.</p>
                            </div>
                        ) : (
                            <div>
                                <h2>No welcome message</h2>
                                <p>Because the feature flag evaluated to false.</p>
                            </div>
                        )}
                    </div>
                )
            }
        `,
        'node.js': dedent`
            const enabledVariant = await client.getFeatureFlag('flag-key', 'distinct_id_of_your_user')
            if (enabledVariant === 'variant-key') {  // replace 'variant-key' with the key of your variant
                // Do something differently for this user
                // Optional: fetch the payload
                const matchedFlagPayload = await client.getFeatureFlagPayload('flag-key', 'distinct_id_of_your_user', enabledVariant)
            }
        `,
        python: dedent`
            enabled_variant = posthog.get_feature_flag('flag-key', 'distinct_id_of_your_user')
            if enabled_variant == 'variant-key': # replace 'variant-key' with the key of your variant
                # Do something differently for this user
                # Optional: fetch the payload
                matched_flag_payload = posthog.get_feature_flag_payload('flag-key', 'distinct_id_of_your_user')
        `,
        php: dedent`
            $enabledVariant = PostHog::getFeatureFlag('flag-key', 'distinct_id_of_your_user')
            if ($enabledVariant === 'variant-key') { # replace 'variant-key' with the key of your variant
                # Do something differently for this user
            }
        `,
        ruby: dedent`
            enabled_variant = posthog.get_feature_flag('flag-key', 'distinct_id_of_your_user')
            if enabled_variant == 'variant-key' # replace 'variant-key' with the key of your variant
                # Do something differently for this user
                # Optional: fetch the payload
                matched_flag_payload = posthog.get_feature_flag_payload('flag-key', 'distinct_id_of_your_user')
            end
        `,
        go: dedent`
            enabledVariant, err := client.GetFeatureFlag(posthog.FeatureFlagPayload{
                Key:        "flag-key",
                DistinctId: "distinct_id_of_your_user",
            })
            if err != nil {
                // Handle error (e.g. capture error and fallback to default behaviour)
            }
            if enabledVariant == "variant-key" { // replace 'variant-key' with the key of your variant
                // Do something differently for this user
            }
        `,
    }

    const langMap: Record<string, string> = {
        javascript: 'javascript',
        react: 'jsx',
        'node.js': 'javascript',
        python: 'python',
        php: 'php',
        ruby: 'ruby',
        go: 'go',
    }

    return <CodeBlock language={langMap[language] || 'javascript'} code={snippets[language] || snippets.javascript} />
})
