import { connect, kea, path, selectors } from 'kea'

import { sdkHealthLogic } from '~/scenes/onboarding/shared/sdkHealth/sdkHealthLogic'

import type { surveysSdkLogicType } from './surveysSdkLogicType'
import { TeamSdkVersions } from './surveyVersionRequirements'

export const surveysSdkLogic = kea<surveysSdkLogicType>([
    path(['scenes', 'surveys', 'surveysSdkLogic']),
    connect(() => ({
        values: [sdkHealthLogic, ['augmentedData as sdkHealthData']],
    })),
    selectors({
        teamSdkVersions: [
            (s) => [s.sdkHealthData],
            (sdkHealthData): TeamSdkVersions => {
                const versions: TeamSdkVersions = {}

                for (const [sdkType, sdkInfo] of Object.entries(sdkHealthData ?? {})) {
                    if (sdkInfo?.allReleases?.length) {
                        // sdk health uses 'web' but we use 'posthog-js' in SURVEY_SDK_REQUIREMENTS
                        const key = sdkType === 'web' ? 'posthog-js' : sdkType
                        versions[key as keyof TeamSdkVersions] = sdkInfo.allReleases[0]?.version ?? null
                    }
                }

                return versions
            },
        ],
    }),
])
