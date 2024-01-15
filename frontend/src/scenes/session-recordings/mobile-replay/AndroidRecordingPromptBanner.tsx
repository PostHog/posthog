import { useActions, useValues } from 'kea'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'
import {
    androidRecordingPromptBannerLogic,
    AndroidRecordingPromptBannerLogicProps,
} from 'scenes/session-recordings/mobile-replay/androidRecordingPromptBannerLogic'

export function AndroidRecordingsPromptBanner(props: AndroidRecordingPromptBannerLogicProps): JSX.Element | null {
    const { shouldPromptUser } = useValues(androidRecordingPromptBannerLogic(props))
    const { openSupportForm } = useActions(supportLogic)

    if (!shouldPromptUser) {
        return null
    }

    return (
        <FlaggedFeature flag={FEATURE_FLAGS.RECRUIT_ANDROID_MOBILE_BETA_TESTERS} match={true}>
            <LemonBanner
                type="info"
                dismissKey="android-recording-beta-prompt"
                action={{
                    children: 'Learn more',
                    to: 'https://github.com/PostHog/posthog-android/blob/main/USAGE.md#android-session-recording',
                    targetBlank: true,
                }}
                className="mb-4"
            >
                <h3 className="mb-0 ml-2">Android Session Replay</h3>
                <div className="ml-2">
                    We're recruiting beta testers for Android Session Replay.{' '}
                    <Link onClick={() => openSupportForm({ kind: 'support', target_area: 'session_replay' })}>
                        Contact support
                    </Link>{' '}
                    to join the test and earn PostHog merch.
                </div>
            </LemonBanner>
        </FlaggedFeature>
    )
}
