import { useValues } from 'kea'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { teamLogic } from 'scenes/teamLogic'

function IOSInstallCocoaPodsSnippet(): JSX.Element {
    return <CodeSnippet language={Language.Ruby}>{'pod "PostHog", "~> 3.0.0"'}</CodeSnippet>
}

function IOSInstallSPMSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.Swift}>
            {`dependencies: [
  .package(url: "https://github.com/PostHog/posthog-ios.git", from: "3.0.0")
]`}
        </CodeSnippet>
    )
}

function IOSSetupSnippet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <CodeSnippet language={Language.Swift}>
            {`import Foundation
import PostHog
import UIKit

class AppDelegate: NSObject, UIApplicationDelegate {
    func application(_: UIApplication, didFinishLaunchingWithOptions _: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        let POSTHOG_API_KEY = "${currentTeam?.api_token}"
        let POSTHOG_HOST = "${window.location.origin}"

        let config = PostHogConfig(apiKey: POSTHOG_API_KEY, host: POSTHOG_HOST)
        PostHogSDK.shared.setup(config)

        return true
    }
}`}
        </CodeSnippet>
    )
}

export function SDKInstallIOSInstructions(): JSX.Element {
    return (
        <>
            <h3>Install via CocoaPods</h3>
            <IOSInstallCocoaPodsSnippet />
            <h3>Or Install via SPM</h3>
            <IOSInstallSPMSnippet />
            <h3>Configure</h3>
            <IOSSetupSnippet />
        </>
    )
}
