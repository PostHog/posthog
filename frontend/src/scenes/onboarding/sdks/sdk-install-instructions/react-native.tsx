import { LemonBanner, Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

export interface RNSetupProps {
    includeReplay?: boolean
}

function RNInstallSnippet({ includeReplay }: RNSetupProps): JSX.Element {
    return (
        <CodeSnippet language={Language.Bash}>
            {`# Expo apps
npx expo install posthog-react-native expo-file-system expo-application expo-device expo-localization${
                includeReplay ? ` posthog-react-native-session-replay` : ''
            } 

# Standard React Native apps
yarn add posthog-react-native @react-native-async-storage/async-storage react-native-device-info${
                includeReplay ? ` posthog-react-native-session-replay` : ''
            } 
# or
npm i -s posthog-react-native @react-native-async-storage/async-storage react-native-device-info${
                includeReplay ? ` posthog-react-native-session-replay` : ''
            } 

# for iOS
cd ios
pod install`}
        </CodeSnippet>
    )
}

function RNSetupSnippet({ includeReplay }: RNSetupProps): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const url = apiHostOrigin()

    return (
        <>
            <p>
                PostHog is most easily used via the <code>PostHogProvider</code> component but if you need to
                instantiate it directly,{' '}
                <Link to="https://posthog.com/docs/libraries/react-native#without-the-posthogprovider">
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
            ${
                includeReplay
                    ? `
            enableSessionReplay: true,
            sessionReplayConfig: {
                // Whether text inputs are masked. Default is true.
                // Password inputs are always masked regardless
                maskAllTextInputs: true,
                // Whether images are masked. Default is true.
                maskAllImages: true,
                // Capture logs automatically. Default is true.
                // Android only (Native Logcat only)
                captureLog: true,
                // Whether network requests are captured in recordings. Default is true
                // Only metric-like data like speed, size, and response code are captured.
                // No data is captured from the request or response body.
                // iOS only
                captureNetworkTelemetry: true,
                // Deboucer delay used to reduce the number of snapshots captured and reduce performance impact. Default is 500ms
                androidDebouncerDelayMs: 500,
                // Deboucer delay used to reduce the number of snapshots captured and reduce performance impact. Default is 1000ms
                iOSdebouncerDelayMs: 1000,
            },`
                    : ''
            }
        }}>
            <RestOfApp />
        </PostHogProvider>
    )
}`}
            </CodeSnippet>
        </>
    )
}

export function SDKInstallRNInstructions(props: RNSetupProps): JSX.Element {
    return (
        <>
            {props.includeReplay ? (
                <LemonBanner type="info">
                    🚧 NOTE: <Link to="https://posthog.com/docs/session-replay/mobile">Mobile recording</Link> is
                    currently in beta. We are keen to gather as much feedback as possible so if you try this out please
                    let us know. You can send feedback via the{' '}
                    <Link to="https://us.posthog.com/#panel=support%3Afeedback%3Asession_replay%3Alow">
                        in-app support panel
                    </Link>{' '}
                    or one of our other <Link to="https://posthog.com/docs/support-options">support options</Link>.
                </LemonBanner>
            ) : null}
            <h3>Install</h3>
            <RNInstallSnippet {...props} />
            <h3>Configure</h3>
            <RNSetupSnippet {...props} />
        </>
    )
}
