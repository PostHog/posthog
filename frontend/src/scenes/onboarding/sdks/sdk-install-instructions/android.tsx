import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

function AndroidInstallSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.Java}>
            {`dependencies {
    implementation 'com.posthog.android:posthog:1.+'
}`}
        </CodeSnippet>
    )
}

function AndroidSetupSnippet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <CodeSnippet language={Language.Java}>
            {`public class SampleApp extends Application {
    private static final String POSTHOG_API_KEY = "${currentTeam?.api_token}";
    private static final String POSTHOG_HOST = "${window.location.origin}";

    @Override
    public void onCreate() {
        // Create a PostHog client with the given context, API key and host
        PostHog posthog = new PostHog.Builder(this, POSTHOG_API_KEY, POSTHOG_HOST)
            .captureApplicationLifecycleEvents() // Record certain application events automatically!
            .recordScreenViews() // Record screen views automatically!
            .build();

        // Set the initialized instance as a globally accessible instance
        PostHog.setSingletonInstance(posthog);

        // Now any time you call PostHog.with, the custom instance will be returned
        PostHog posthog = PostHog.with(this);
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
