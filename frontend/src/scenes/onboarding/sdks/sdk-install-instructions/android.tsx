import { useValues } from 'kea'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
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
        // check https://posthog.com/docs/session-replay/installation?tab=Android
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
            <h3>Install</h3>
            <AndroidInstallSnippet />
            <h3>Configure</h3>
            <AndroidSetupSnippet {...props} />
        </>
    )
}

export function SDKInstallAndroidTrackScreenInstructions(): JSX.Element {
    return (
        <>
            <p>
                With <code>captureScreenViews = true</code>, PostHog will try to record all screen changes
                automatically.
            </p>
            <p>
                If you want to manually send a new screen capture event, use the <code>screen</code> function.
            </p>
            <CodeSnippet language={Language.Kotlin}>{`import com.posthog.PostHog

PostHog.screen(
    screenTitle = "Dashboard",
    properties = mapOf(
        "background" to "blue",
        "hero" to "superhog"
    )
)`}</CodeSnippet>
        </>
    )
}
