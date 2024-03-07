import { useValues } from 'kea'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

function AndroidInstallSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.Kotlin}>
            {`dependencies {
    implementation("com.posthog:posthog-android:3.+")
}`}
        </CodeSnippet>
    )
}

function AndroidSetupSnippet(): JSX.Element {
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

        // Setup PostHog with the given Context and Config
        PostHogAndroid.setup(this, config)
    }`}
        </CodeSnippet>
    )
}

export function SDKInstallAndroidInstructions(): JSX.Element {
    return (
        <>
            <h3>Install</h3>
            <AndroidInstallSnippet />
            <h3>Configure</h3>
            <AndroidSetupSnippet />
        </>
    )
}
