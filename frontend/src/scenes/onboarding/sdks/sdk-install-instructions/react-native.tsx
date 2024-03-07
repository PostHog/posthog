import { Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

export function SDKInstallRNInstructions(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const url = apiHostOrigin()

    return (
        <>
            <h3 className="mt-4">Install</h3>
            <CodeSnippet language={Language.Bash}>
                {`# Expo apps
expo install posthog-react-native expo-file-system expo-application expo-device expo-localization

# Standard React Native apps
yarn add posthog-react-native @react-native-async-storage/async-storage react-native-device-info
# or
npm i -s posthog-react-native @react-native-async-storage/async-storage react-native-device-info

# for iOS
cd ios
pod install`}
            </CodeSnippet>
            <h3 className="mt-4">Configure</h3>
            <p>
                PostHog is most easily used via the <code>PostHogProvider</code> component but if you need to
                instantiate it directly,{' '}
                <Link to="https://posthog.com/docs/integrate/client/react-native#without-the-posthogprovider">
                    check out the docs
                </Link>{' '}
                which explain how to do this correctly.
            </p>
            <CodeSnippet language={Language.JSX}>
                {`// App.(js|ts)
import { PostHogProvider } from 'posthog-react-native'
...

export function MyApp() {
    return (
        <PostHogProvider apiKey="${currentTeam?.api_token}" options={{
            host: "${url}",
        }}>
            <RestOfApp />
        </PostHogProvider>
    )
}`}
            </CodeSnippet>
        </>
    )
}
