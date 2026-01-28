import { afterMount, connect, kea, key, path, props, selectors } from 'kea'

import {
    AugmentedTeamSdkVersionsInfo,
    sidePanelSdkDoctorLogic,
} from '~/layout/navigation-3000/sidepanel/panels/sidePanelSdkDoctorLogic'

import type { versionCheckerLogicType } from './versionCheckerLogicType'

export type SDKVersionWarning = {
    latestUsedVersion: string
    latestAvailableVersion: string
    level: 'warning' | 'info' | 'error'
}

export interface VersionCheckerLogicProps {
    teamId: number | null
}

export const versionCheckerLogic = kea<versionCheckerLogicType>([
    props({ teamId: null } as VersionCheckerLogicProps),
    key(({ teamId }) => teamId || 'no-team-id'),
    path((key) => ['components', 'VersionChecker', 'versionCheckerLogic', key]),

    connect({
        values: [sidePanelSdkDoctorLogic, ['augmentedData', 'rawDataLoading']],
        actions: [sidePanelSdkDoctorLogic, ['loadRawData']],
    }),

    selectors({
        versionWarning: [
            (s) => [s.augmentedData, s.rawDataLoading],
            (augmentedData: AugmentedTeamSdkVersionsInfo, loading: boolean): SDKVersionWarning | null => {
                if (loading || !augmentedData?.web) {
                    return null
                }

                const webSdk = augmentedData.web
                if (!webSdk.needsUpdating) {
                    return null
                }

                const latestRelease = webSdk.allReleases[0]
                if (!latestRelease) {
                    return null
                }

                // Don't show warning if the most recent version being used is already the latest
                if (latestRelease.version === latestRelease.latestVersion) {
                    return null
                }

                // Map SDK doctor's isOutdated/isOld to our warning levels
                let level: 'warning' | 'info' | 'error' = 'warning'
                if (webSdk.isOutdated) {
                    level = 'error'
                } else if (webSdk.isOld) {
                    level = 'warning'
                }

                return {
                    latestUsedVersion: latestRelease.version,
                    latestAvailableVersion: latestRelease.latestVersion,
                    level,
                }
            },
        ],
    }),

    afterMount(({ actions, values }) => {
        // Trigger SDK Doctor to load data if not already loaded
        if (!values.augmentedData?.web && !values.rawDataLoading) {
            actions.loadRawData()
        }
    }),
])
