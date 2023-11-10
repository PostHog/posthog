import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

function IOSInstallSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.Ruby}>
            {'pod "PostHog", "~> 1.1" # Cocoapods \n# OR \ngithub "posthog/posthog-ios" # Carthage'}
        </CodeSnippet>
    )
}

function IOS_OBJ_C_SetupSnippet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <CodeSnippet language={Language.ObjectiveC}>
            {`#import <PostHog/PHGPostHog.h>\n#import <PostHog/PHGPostHogConfiguration.h>\n\nPHGPostHogConfiguration *configuration = [PHGPostHogConfiguration configurationWithApiKey:@"${currentTeam?.api_token}" host:@"${window.location.origin}"];\n\nconfiguration.captureApplicationLifecycleEvents = YES; // Record certain application events automatically!\nconfiguration.recordScreenViews = YES; // Record screen views automatically!\n\n[PHGPostHog setupWithConfiguration:configuration];`}
        </CodeSnippet>
    )
}

function IOS_SWIFT_SetupSnippet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <CodeSnippet language={Language.Swift}>
            {`import PostHog\n\nlet configuration = PHGPostHogConfiguration(apiKey: "${currentTeam?.api_token}", host: "${window.location.origin}")\n\nconfiguration.captureApplicationLifecycleEvents = true; // Record certain application events automatically!\nconfiguration.recordScreenViews = true; // Record screen views automatically!\n\nPHGPostHog.setup(with: configuration)\nlet posthog = PHGPostHog.shared()`}
        </CodeSnippet>
    )
}

export function SDKInstallIOSInstructions(): JSX.Element {
    return (
        <>
            <h3>Install</h3>
            <IOSInstallSnippet />
            <h3>Configure Swift</h3>
            <IOS_SWIFT_SetupSnippet />
            <h3>Or configure Objective-C</h3>
            <IOS_OBJ_C_SetupSnippet />
        </>
    )
}
