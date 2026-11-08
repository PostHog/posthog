import { useValues } from 'kea'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { Link } from 'lib/lemon-ui/Link'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

export interface iOSSetupProps {
    includeReplay?: boolean
    includeSurveys?: boolean
    includeExperimentalSpi?: boolean
}

function IOSInstallSPMSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.Swift}>
            {`dependencies: [
  .package(url: "https://github.com/PostHog/posthog-ios.git", from: "4.0.0")
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
        config.sessionReplayConfig.maskAllTextInputs = true`,
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
        let POSTHOG_PROJECT_TOKEN = "${currentTeam?.api_token}"
        let POSTHOG_HOST = "${apiHostOrigin()}"

        let config = PostHogConfig(projectToken: POSTHOG_PROJECT_TOKEN, host: POSTHOG_HOST)
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
            <h3>Install via Swift Package Manager</h3>
            <p>
                PostHog requires Xcode 26 or later, and iOS 15, macOS 11, tvOS 15, watchOS 10, or visionOS 1 or later.
            </p>
            <IOSInstallSPMSnippet />
            <p>
                Using CocoaPods? Version 4 is only published to Swift Package Manager. Version 3 stays on CocoaPods (
                <code>pod "PostHog", "~&gt; 3.0"</code>) but gets no new releases. To switch, see{' '}
                <Link to="https://posthog.com/docs/libraries/ios#upgrading-from-version-3-to-version-4" target="_blank">
                    upgrading from version 3 to version 4
                </Link>
                .
            </p>
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
