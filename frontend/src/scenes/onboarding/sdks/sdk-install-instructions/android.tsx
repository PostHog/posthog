import { Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

export interface AndroidSetupProps {
    includeReplay?: boolean
}

function AndroidInstallSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.Kotlin}>
            {`dependencies {
    implementation("com.posthog:posthog-android:3.+")
}`}
        </CodeSnippet>
    )
}

function AndroidSetupSnippet({ includeReplay }: AndroidSetupProps): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <CodeSnippet language={Language.Kotlin}>
            {`class SampleApp : Application() {

    companion object {
        const val POSTHOG_API_KEY = "${currentTeam?.api_token}"
        const val POSTHOG_HOST = "${apiHostOrigin()}"
    }

    override fun onCreate() {
        super.onCreate()

        // Create a PostHog Config with the given API key and host
        val config = PostHogAndroidConfig(
            apiKey = POSTHOG_API_KEY,
            host = POSTHOG_HOST
        )
        ${
            includeReplay
                ? `
        // check https://posthog.com/docs/session-replay/android#installation
        // for more config and to learn about how we capture sessions on mobile
        // and what to expect
        config.sessionReplay = true
        // choose whether to mask images or text
        config.sessionReplayConfig.maskAllImages = false
        config.sessionReplayConfig.maskAllTextInputs = true
        // screenshot is disabled by default
        // The screenshot may contain sensitive information, use with caution
        config.sessionReplayConfig.screenshot = true`
                : ''
        }

        // Setup PostHog with the given Context and Config
        PostHogAndroid.setup(this, config)
    }
}`}
        </CodeSnippet>
    )
}

export function SDKInstallAndroidInstructions(props: AndroidSetupProps): JSX.Element {
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
            <AndroidInstallSnippet />
            <h3>Configure</h3>
            <AndroidSetupSnippet {...props} />
        </>
    )
}
