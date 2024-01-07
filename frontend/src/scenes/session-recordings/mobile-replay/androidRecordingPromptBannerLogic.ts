import { connect, kea, path, props, selectors } from 'kea'
import { versionCheckerLogic, VersionCheckerLogicProps } from 'lib/components/VersionChecker/versionCheckerLogic'
import posthog from 'posthog-js'

import type { androidRecordingPromptBannerLogicType } from './androidRecordingPromptBannerLogicType'

export const androidRecordingPromptBannerLogic = kea<androidRecordingPromptBannerLogicType>([
    path(['scenes', 'session-recordings', 'SessionRecordings']),

    props({} as VersionCheckerLogicProps),

    connect((props: VersionCheckerLogicProps) => ({
        values: [versionCheckerLogic(props), ['usedVersions']],
    })),

    selectors({
        shouldPromptUser: [
            (s) => [s.usedVersions],
            (usedVersions) => {
                const isUsingAndroid = (usedVersions?.length || 0) > 0
                if (isUsingAndroid) {
                    posthog.capture('replay visitor has android events', { androidVersions: usedVersions })
                }
                return isUsingAndroid
            },
        ],
    }),
])
