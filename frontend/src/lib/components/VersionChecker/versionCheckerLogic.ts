import { afterMount, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { HogQLQuery, NodeKind } from '~/queries/schema'

import type { versionCheckerLogicType } from './versionCheckerLogicType'

const CHECK_INTERVAL_MS = 1000 * 60 * 60 // 6 hour

export type SDKVersion = {
    version: string
    timestamp?: string
}

export type SDKVersionWarning = {
    currentVersion: string
    latestVersion: string
    diff: number
    level: 'warning' | 'info' | 'error'
}

export const versionCheckerLogic = kea<versionCheckerLogicType>([
    path(['components', 'VersionChecker', 'versionCheckerLogic']),
    loaders({
        availableVersions: [
            null as SDKVersion[] | null,
            {
                loadAvailableVersions: async () => {
                    const versions = await fetch('https://api.github.com/repos/posthog/posthog-js/tags').then((r) =>
                        r.json()
                    )

                    return versions.map((version: any) => ({
                        version: version.name.replace('v', ''),
                    }))
                },
            },
        ],
        usedVersions: [
            null as SDKVersion[] | null,
            {
                loadUsedVersions: async () => {
                    const query: HogQLQuery = {
                        kind: NodeKind.HogQLQuery,
                        query: `SELECT properties.$lib_version AS lib_version, max(timestamp) AS latest_timestamp, count(lib_version) as count
                                FROM events
                                WHERE timestamp >= now() - INTERVAL 1 DAY 
                                AND timestamp <= now()
                                AND properties.$lib = 'web'
                                GROUP BY lib_version
                                ORDER BY latest_timestamp DESC
                                limit 10`,
                    }

                    const res = await api.query(query)

                    return (
                        res.results?.map((x) => ({
                            version: x[0],
                            timestamp: x[1],
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
                loadUsedVersionsSuccess: () => Date.now(),
            },
        ],
    }),

    selectors({
        versionWarning: [
            (s) => [s.availableVersions, s.usedVersions],
            (availableVersions, usedVersions): SDKVersionWarning | null => {
                if (!availableVersions?.length || !usedVersions?.length) {
                    return null
                }

                const latestVersion = availableVersions[0].version
                const currentVersion = usedVersions[0].version

                if (latestVersion === currentVersion) {
                    return null
                }

                let diff = availableVersions.findIndex((v) => v.version === currentVersion)
                diff = diff === -1 ? availableVersions.length : diff

                return {
                    currentVersion,
                    latestVersion,
                    diff,
                    level: diff > 20 ? 'error' : diff > 10 ? 'warning' : 'info',
                }
            },
        ],
    }),

    afterMount(({ actions, values }) => {
        if (values.lastCheckTimestamp < Date.now() - CHECK_INTERVAL_MS) {
            actions.loadAvailableVersions()
            actions.loadUsedVersions()
        }
    }),
])
