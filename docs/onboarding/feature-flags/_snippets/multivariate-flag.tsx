import { memo } from 'react'

import { useMDXComponents } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

export const MultivariateFlagSnippet = memo(({ language = 'javascript' }: { language?: string }): JSX.Element => {
    const { CodeBlock, dedent } = useMDXComponents()

    const snippets: Record<string, string> = {
        javascript: dedent`
            const matchedFlag = posthog.getFeatureFlagResult('flag-key')
            if (matchedFlag?.variant == 'variant-key') { // replace 'variant-key' with the key of your variant
                // Do something differently for this user
                // Optional: read the payload from the same result
                const matchedFlagPayload = matchedFlag?.payload
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
            const flags = await client.evaluateFlags('distinct_id_of_your_user', { flagKeys: ['flag-key'] })
            const enabledVariant = flags.getFlag('flag-key')
            if (enabledVariant === 'variant-key') {  // replace 'variant-key' with the key of your variant
                // Do something differently for this user
                // Optional: fetch the payload
                const matchedFlagPayload = flags.getFlagPayload('flag-key')
            }
        `,
        python: dedent`
            flags = posthog.evaluate_flags('distinct_id_of_your_user', flag_keys=['flag-key'])
            enabled_variant = flags.get_flag('flag-key')
            if enabled_variant == 'variant-key': # replace 'variant-key' with the key of your variant
                # Do something differently for this user
                # Optional: fetch the payload
                matched_flag_payload = flags.get_flag_payload('flag-key')
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
            flags, err := client.EvaluateFlags(posthog.EvaluateFlagsPayload{
                DistinctId: "distinct_id_of_your_user",
                FlagKeys:   []string{"flag-key"},
            })
            if err != nil {
                // Handle error (e.g. capture error and fallback to default behaviour)
            }
            var enabledVariant interface{}
            if flags != nil {
                enabledVariant = flags.GetFlag("flag-key")
            }
            if enabledVariant == "variant-key" { // replace 'variant-key' with the key of your variant
                // Do something differently for this user
                // Optional: fetch the payload
                matchedFlagPayload := flags.GetFlagPayload("flag-key")
                _ = matchedFlagPayload
            }
        `,
        dotnet: dedent`
            var flags = await posthog.EvaluateFlagsAsync("distinct_id_of_your_user");
            var enabledVariant = flags.GetFlag("flag-key")?.VariantKey;

            if (enabledVariant == "variant-key") // replace "variant-key" with the key of your variant
            {
                // Do something differently for this user
                // Optional: fetch the payload
                var matchedFlagPayload = flags.GetFlagPayload("flag-key");
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
        dotnet: 'csharp',
    }

    return <CodeBlock language={langMap[language] || 'javascript'} code={snippets[language] || snippets.javascript} />
})
