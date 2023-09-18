import { Link } from '@posthog/lemon-ui'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

function ServerSideWarning(): JSX.Element {
    return (
        <div className="warning">
            <p>
                <b>Warning:</b> Server side experiment metrics require you to manually send the feature flag
                information.{' '}
                <Link to="https://posthog.com/tutorials/experiments#step-2-sending-the-right-events" target="_blank">
                    See this tutorial for more information.
                </Link>
            </p>
        </div>
    )
}

interface SnippetProps {
    flagKey: string
    variant: string
}

export function NodeJSSnippet({ flagKey, variant }: SnippetProps): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.JavaScript} wrap>
                {`const experimentFlagValue = await client.getFeatureFlag('${flagKey}', 'user distinct id')

if (experimentFlagValue === '${variant}' ) {
    // Do something differently for this user
} else {
    // It's a good idea to let control variant always be the default behaviour,
    // so if something goes wrong with flag evaluation, you don't break your app.
}`}
            </CodeSnippet>
            <ServerSideWarning />
        </>
    )
}

export function JSSnippet({ flagKey, variant }: SnippetProps): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.JavaScript} wrap>
                {`if (posthog.getFeatureFlag('${flagKey}') === '${variant}') {
    // Do something differently for this user
} else {
    // It's a good idea to let control variant always be the default behaviour,
    // so if something goes wrong with flag evaluation, you don't break your app.
}`}
            </CodeSnippet>
            <b>Test that it works</b>
            <CodeSnippet language={Language.JavaScript} wrap>
                {`posthog.featureFlags.override({'${flagKey}': '${variant}'})`}
            </CodeSnippet>
        </>
    )
}

export function RNSnippet({ flagKey, variant }: SnippetProps): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.JavaScript} wrap>
                {`if (posthog.getFeatureFlag('${flagKey}') === '${variant}') {
    // Do something differently for this user
} else {
    // It's a good idea to let control variant always be the default behaviour,
    // so if something goes wrong with flag evaluation, you don't break your app.
}`}
            </CodeSnippet>
        </>
    )
}

export function PHPSnippet({ flagKey, variant }: SnippetProps): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.PHP} wrap>
                {`if (PostHog::getFeatureFlag('${flagKey}', 'user distinct id') == '${variant}') {
    // Do something differently for this user
} else {
    // It's a good idea to let control variant always be the default behaviour,
    // so if something goes wrong with flag evaluation, you don't break your app.
}`}
            </CodeSnippet>
            <ServerSideWarning />
        </>
    )
}

export function GolangSnippet({ flagKey, variant }: SnippetProps): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.Go} wrap>
                {`experimentFlagValue, err := client.GetFeatureFlag(
                    FeatureFlagPayload{
                        Key:        '${flagKey}',
                        DistinctId: "distinct-id",
                    })

if (experimentFlagValue == '${variant}' ) {
    // Do something differently for this user
} else {
    // It's a good idea to let control variant always be the default behaviour,
    // so if something goes wrong with flag evaluation, you don't break your app.
}`}
            </CodeSnippet>
            <ServerSideWarning />
        </>
    )
}

export function RubySnippet({ flagKey, variant }: SnippetProps): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.Ruby} wrap>
                {`experimentFlagValue = posthog.get_feature_flag('${flagKey}', 'user distinct id')


if experimentFlagValue == '${variant}'
    # Do something differently for this user
else
    # It's a good idea to let control variant always be the default behaviour,
    # so if something goes wrong with flag evaluation, you don't break your app.
end
`}
            </CodeSnippet>
            <ServerSideWarning />
        </>
    )
}

export function PythonSnippet({ flagKey, variant }: SnippetProps): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.Python} wrap>
                {`experiment_flag_value = posthog.get_feature_flag("${flagKey}", "user_distinct_id"):

if experiment_flag_value == '${variant}':
    # Do something differently for this user
else:
    # It's a good idea to let control variant always be the default behaviour,
    # so if something goes wrong with flag evaluation, you don't break your app.
`}
            </CodeSnippet>
            <ServerSideWarning />
        </>
    )
}
