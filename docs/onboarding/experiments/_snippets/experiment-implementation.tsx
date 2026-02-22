import { memo } from 'react'
import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const ExperimentImplementationSnippet = memo(({ language = 'javascript' }: { language?: string }): JSX.Element => {
    const { CodeBlock, dedent } = useMDXComponents()

    const snippets: Record<string, string> = {
        javascript: dedent`
            const result = posthog.getFeatureFlagResult('your-experiment-feature-flag')
            if (result?.variant === 'test') {
                // Do something differently for this user
            } else {
                // It's a good idea to let control variant always be the default behaviour,
                // so if something goes wrong with flag evaluation, you don't break your app.
            }

            // Test that it works
            posthog.featureFlags.overrideFeatureFlags({ flags: {'your-experiment-feature-flag': 'test'} })
        `,
        react: dedent`
            // You can either use the useFeatureFlagResult hook,
            // or you can use the feature flags component - https://posthog.com/docs/libraries/react#feature-flags-react-component

            // Method one: using the useFeatureFlagResult hook
            import { useFeatureFlagResult } from '@posthog/react'

            function App() {
                const result = useFeatureFlagResult('your-experiment-feature-flag')
                if (result?.variant === 'test') {
                    // do something
                }
            }

            // Method two: using the feature flags component
            import { PostHogFeature } from '@posthog/react'

            function App() {
                return (
                    <PostHogFeature flag='your-experiment-feature-flag' match='test'>
                        <div>
                            {/* the component to show */}
                        </div>
                    </PostHogFeature>
                )
            }

            // You can also test your code by overriding the feature flag:
            posthog.featureFlags.overrideFeatureFlags({ flags: {'your-experiment-feature-flag': 'test'} })
        `,
        'react-native': dedent`
            const result = posthog.getFeatureFlagResult('your-experiment-feature-flag')
            if (result?.variant === 'test') {
                // Do something differently for this user
            } else {
                // It's a good idea to let control variant always be the default behaviour,
                // so if something goes wrong with flag evaluation, you don't break your app.
            }
        `,
        'node.js': dedent`
            const result = await client.getFeatureFlagResult('your-experiment-feature-flag', 'user distinct id')
            if (result?.variant === 'test') {
                // Do something differently for this user
            } else {
                // It's a good idea to let control variant always be the default behaviour,
                // so if something goes wrong with flag evaluation, you don't break your app.
            }
        `,
        python: dedent`
            result = posthog.get_feature_flag_result("your-experiment-feature-flag", "user_distinct_id")
            if result and result.variant == 'test':
                # Do something differently for this user
            else:
                # It's a good idea to let control variant always be the default behaviour,
                # so if something goes wrong with flag evaluation, you don't break your app.
        `,
        php: dedent`
            $result = PostHog::getFeatureFlagResult('your-experiment-feature-flag', 'user distinct id');
            if ($result?->getVariant() === 'test') {
                // Do something differently for this user
            } else {
                // It's a good idea to let control variant always be the default behaviour,
                // so if something goes wrong with flag evaluation, you don't break your app.
            }
        `,
        ruby: dedent`
            result = posthog.get_feature_flag_result('your-experiment-feature-flag', 'user distinct id')
            if result&.variant == 'test'
                # Do something differently for this user
            else
                # It's a good idea to let control variant always be the default behaviour,
                # so if something goes wrong with flag evaluation, you don't break your app.
            end
        `,
        go: dedent`
            result, err := client.GetFeatureFlagResult(posthog.FeatureFlagPayload{
                Key:        "your-experiment-feature-flag",
                DistinctId: "distinct-id",
            })
            if err != nil {
                // Handle error (e.g. capture error and fallback to default behaviour)
            }
            if result.Variant != nil && *result.Variant == "test" {
                // Do something differently for this user
            } else {
                // It's a good idea to let control variant always be the default behaviour,
                // so if something goes wrong with flag evaluation, you don't break your app.
            }
        `,
        android: dedent`
            val result = PostHog.getFeatureFlagResult("your-experiment-feature-flag")
            if (result?.variant == "test") {
                // do something
            } else {
                // It's a good idea to let control variant always be the default behaviour,
                // so if something goes wrong with flag evaluation, you don't break your app.
            }
        `,
        ios: dedent`
            let result = PostHogSDK.shared.getFeatureFlagResult("your-experiment-feature-flag")
            if result?.variant == "test" {
                // do something
            } else {
                // It's a good idea to let control variant always be the default behaviour,
                // so if something goes wrong with flag evaluation, you don't break your app.
            }
        `,
        flutter: dedent`
            final result = await Posthog().getFeatureFlagResult('your-experiment-feature-flag');
            if (result?.variant == 'test') {
                // Do something differently for this user
            } else {
                // It's a good idea to let control variant always be the default behaviour,
                // so if something goes wrong with flag evaluation, you don't break your app.
            }
        `,
    }

    const langMap: Record<string, string> = {
        javascript: 'javascript',
        react: 'jsx',
        'react-native': 'javascript',
        'node.js': 'javascript',
        python: 'python',
        php: 'php',
        ruby: 'ruby',
        go: 'go',
        android: 'kotlin',
        ios: 'swift',
        flutter: 'dart',
    }

    return <CodeBlock language={langMap[language] || 'javascript'} code={snippets[language] || snippets.javascript} />
})
