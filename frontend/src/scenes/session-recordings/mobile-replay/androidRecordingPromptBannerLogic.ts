import { afterMount, kea, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { SDKVersion } from 'lib/components/VersionChecker/versionCheckerLogic'
import posthog from 'posthog-js'

import { HogQLQuery, NodeKind } from '~/queries/schema'

import type { androidRecordingPromptBannerLogicType } from './androidRecordingPromptBannerLogicType'

const CHECK_INTERVAL_MS = 1000 * 60 * 60 // 6 hour

export interface AndroidRecordingPromptBannerLogicProps {
    context: 'home' | 'events' | 'replay'
}

export type AndroidEventCount = {
    version: string
    count?: number
}

export const androidRecordingPromptBannerLogic = kea<androidRecordingPromptBannerLogicType>([
    path(['scenes', 'session-recordings', 'SessionRecordings']),
    props({} as AndroidRecordingPromptBannerLogicProps),
    loaders({
        androidVersions: [
            null as SDKVersion[] | null,
            {
                loadAndroidLibVersions: async () => {
                    const query: HogQLQuery = {
                        kind: NodeKind.HogQLQuery,
                        query: `SELECT properties.$lib_version AS lib_version,
                                       max(timestamp) AS latest_timestamp,
                                       count(lib_version) as count
                                FROM events
                                WHERE timestamp >= now() - INTERVAL 30 DAY
                                  AND timestamp <= now()
                                  AND properties.$lib in ('posthog-android')
                                GROUP BY lib_version
                                ORDER BY latest_timestamp DESC
                                    limit 10`,
                    }

                    const res = await api.query(query)

                    return (
                        res.results?.map((x) => ({
                            version: x[0],
                            count: x[2],
                        })) ?? null
                    )
                },
            },
        ],
    }),
    reducers({
        lastCheckTimestamp: [
            0,
            { persist: true },
            {
                loadAndroidLibVersionsSuccess: () => Date.now(),
            },
        ],
    }),

    selectors(({ props }) => ({
        shouldPromptUser: [
            (s) => [s.androidVersions],
            (androidVersions) => {
                const isUsingAndroid = (androidVersions?.length || 0) > 0
                if (isUsingAndroid) {
                    posthog.capture(`${props.context} visitor has android events`, { androidVersions })
                }
                return isUsingAndroid
            },
        ],
    })),

    afterMount(({ actions, values }) => {
        if (values.lastCheckTimestamp < Date.now() - CHECK_INTERVAL_MS) {
            actions.loadAndroidLibVersions()
        }
    }),
])
