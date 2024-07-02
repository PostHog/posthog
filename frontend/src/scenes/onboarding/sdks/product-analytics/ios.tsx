import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { OnboardingStepKey } from 'scenes/onboarding/onboardingLogic'
import { urls } from 'scenes/urls'

import { SDKKey } from '~/types'

import { SDKInstallIOSInstructions } from '../sdk-install-instructions'
import { PersonModeEventPropertyInstructions } from '../shared-snippets'

function IOSCaptureSnippet(): JSX.Element {
    return <CodeSnippet language={Language.Swift}>{`PostHogSDK.shared.capture("Test Event")`}</CodeSnippet>
}

export function AdvertiseiOSReplay({
    context,
}: {
    context: 'product-analytics-onboarding' | 'flags-onboarding'
}): JSX.Element {
    return (
        <div>
            <LemonDivider className="my-8" />
            <LemonBanner type="info">
                <h3>
                    Session Replay for iOS <LemonTag type="highlight">NEW</LemonTag>
                </h3>
                <div>
                    Session replay is now in beta for iOS.{' '}
                    <Link
                        to={urls.onboarding('session_replay', OnboardingStepKey.INSTALL, SDKKey.IOS)}
                        data-attr={`${context}-ios-replay-cta`}
                    >
                        Learn how to set it up
                    </Link>
                </div>
            </LemonBanner>
        </div>
    )
}

export function ProductAnalyticsIOSInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallIOSInstructions />
            <h3>Send an event</h3>
            <IOSCaptureSnippet />
            <PersonModeEventPropertyInstructions />
            <FlaggedFeature flag={FEATURE_FLAGS.SESSION_REPLAY_MOBILE_ONBOARDING} match={true}>
                <AdvertiseiOSReplay context="product-analytics-onboarding" />
            </FlaggedFeature>
        </>
    )
}
