import { useValues } from 'kea'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

export interface iOSSetupProps {
    includeReplay?: boolean
    includeSurveys?: boolean
    includeExperimentalSpi?: boolean
}

function IOSInstallCocoaPodsSnippet(): JSX.Element {
    return <CodeSnippet language={Language.Ruby}>{'pod "PostHog", "~> 3.0"'}</CodeSnippet>
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

function IOSSetupSnippet(props: iOSSetupProps): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    const configOptions = [
        props.includeReplay &&
            `// check https://posthog.com/docs/session-replay/installation?tab=iOS
        // for more config and to learn about how we capture sessions on mobile
        // and what to expect
        config.sessionReplay = true
        // choose whether to mask images or text
        config.sessionReplayConfig.maskAllImages = false
        config.sessionReplayConfig.maskAllTextInputs = true
        // screenshot is disabled by default
        // The screenshot may contain sensitive information, use with caution
        config.sessionReplayConfig.screenshotMode = true`,
        props.includeSurveys && `config.surveys = true`,
    ]
        .filter(Boolean)
        .join('\n')

    const configSection = configOptions ? configOptions : ''

    return (
        <CodeSnippet language={Language.Swift}>
            {`import Foundation
${props.includeExperimentalSpi ? '@_spi(Experimental) import PostHog' : 'import PostHog'}
import UIKit

class AppDelegate: NSObject, UIApplicationDelegate {
    func application(_: UIApplication, didFinishLaunchingWithOptions _: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        let POSTHOG_API_KEY = "${currentTeam?.api_token}"
        let POSTHOG_HOST = "${apiHostOrigin()}"

        let config = PostHogConfig(apiKey: POSTHOG_API_KEY, host: POSTHOG_HOST)
        ${configSection}
        PostHogSDK.shared.setup(config)

        return true
    }
}`}
        </CodeSnippet>
    )
}

export function SDKInstallIOSInstructions(props: iOSSetupProps): JSX.Element {
    return (
        <>
            <h3>Install via CocoaPods</h3>
            <IOSInstallCocoaPodsSnippet />
            <h3>Or Install via SPM</h3>
            <IOSInstallSPMSnippet />
            <h3>Configure</h3>
            <IOSSetupSnippet {...props} />
        </>
    )
}

export function SDKInstallIOSTrackScreenInstructions(): JSX.Element {
    return (
        <>
            <p>
                With <code>configuration.captureScreenViews</code> set as <code>true</code>, PostHog will try to record
                all screen changes automatically.
            </p>
            <p>
                If you want to manually send a new screen capture event, use the <code>screen</code> function.
            </p>
            <CodeSnippet
                language={Language.Swift}
            >{`PostHogSDK.shared.screen("Dashboard", properties: ["fromIcon": "bottom"])`}</CodeSnippet>
        </>
    )
}
