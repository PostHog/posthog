import { connect, kea, path, selectors } from 'kea'

import { sidePanelSdkDoctorLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelSdkDoctorLogic'

import { TeamSdkVersions } from './surveyVersionRequirements'
import type { surveysSdkLogicType } from './surveysSdkLogicType'

export const surveysSdkLogic = kea<surveysSdkLogicType>([
    path(['scenes', 'surveys', 'surveysSdkLogic']),
    connect(() => ({
        values: [sidePanelSdkDoctorLogic, ['augmentedData as sdkDoctorData']],
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
