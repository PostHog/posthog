import { connect, kea, path, selectors } from 'kea'

import { sdkDoctorLogic } from '~/scenes/onboarding/sdks/sdkDoctorLogic'

import type { surveysSdkLogicType } from './surveysSdkLogicType'
import { TeamSdkVersions } from './surveyVersionRequirements'

export const surveysSdkLogic = kea<surveysSdkLogicType>([
    path(['scenes', 'surveys', 'surveysSdkLogic']),
    connect(() => ({
        values: [sdkDoctorLogic, ['augmentedData as sdkDoctorData']],
    })),
    selectors({
        teamSdkVersions: [
            (s) => [s.sdkDoctorData],
            (sdkDoctorData): TeamSdkVersions => {
                const versions: TeamSdkVersions = {}

                for (const [sdkType, sdkInfo] of Object.entries(sdkDoctorData ?? {})) {
                    if (sdkInfo?.allReleases?.length) {
                        // sdk doctor uses 'web' but we use 'posthog-js' in SURVEY_SDK_REQUIREMENTS
                        const key = sdkType === 'web' ? 'posthog-js' : sdkType
                        versions[key as keyof TeamSdkVersions] = sdkInfo.allReleases[0]?.version ?? null
                    }
                }

                return versions
            },
        ],
    }),
])
