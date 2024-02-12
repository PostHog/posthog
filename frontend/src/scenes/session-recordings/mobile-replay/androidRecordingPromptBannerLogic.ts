import { afterMount, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import posthog from 'posthog-js'

import { HogQLQuery, NodeKind } from '~/queries/schema'
import { hogql } from '~/queries/utils'

import type { androidRecordingPromptBannerLogicType } from './androidRecordingPromptBannerLogicType'

export interface AndroidRecordingPromptBannerLogicProps {
    context: 'home' | 'events' | 'replay'
}

export type AndroidEventCount = {
    version: string
    count?: number
}

export const androidRecordingPromptBannerLogic = kea<androidRecordingPromptBannerLogicType>([
    path(['scenes', 'session-recordings', 'SessionRecordings']),
    key((props) => props.context),
    props({} as AndroidRecordingPromptBannerLogicProps),
    loaders(({ values }) => ({
        androidVersions: [
            [] as AndroidEventCount[],
            {
                loadAndroidLibVersions: async () => {
                    if (values.androidVersions && values.androidVersions.length > 0) {
                        // if we know they ever had android events, don't check again
                        return values.androidVersions
                    }

                    const query: HogQLQuery = {
                        kind: NodeKind.HogQLQuery,
                        query: hogql`SELECT properties.$lib_version AS lib_version,
                                       max(timestamp)          AS latest_timestamp,
                                       count(lib_version) as count
                                FROM events
                                WHERE timestamp >= now() - INTERVAL 30 DAY
                                  AND timestamp <= now()
                                  AND properties.$lib = 'posthog-android'
                                GROUP BY lib_version
                                ORDER BY latest_timestamp DESC
                                    limit 10`,
                    }

                    const res = await api.query(query)

                    return (
                        res.results?.map((x) => ({
                            version: x[0],
                            count: x[2],
                        })) ?? []
                    )
                },
            },
        ],
    })),
    reducers({
        androidVersions: [
            // as a reducer only so we can persist it
            [] as AndroidEventCount[],
            { persist: true },
            {
                loadAndroidLibVersionsSuccess: (_, { androidVersions }) => {
                    return androidVersions ?? []
                },
            },
        ],
    }),

    selectors({
        shouldPromptUser: [
            (s) => [s.androidVersions],
            (androidVersions) => {
                return (androidVersions?.length || 0) > 0
            },
        ],
    }),

    subscriptions(({ values, props }) => ({
        shouldPromptUser: (value, oldvalue) => {
            // not a falsy check since we don't care when oldvalue is undefined
            // we don't need multiple copies of this event so try to only emit it when `shouldPromptUser` changes to true
            if (value === true && oldvalue === false) {
                posthog.capture('visitor has android events', {
                    androidVersions: values.androidVersions,
                    scene: props.context,
                })
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadAndroidLibVersions()
    }),
])
