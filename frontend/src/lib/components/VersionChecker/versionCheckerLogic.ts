import { actions, afterMount, kea, listeners, path, reducers, sharedListeners } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import { HogQLQuery, NodeKind } from '~/queries/schema'
import { hogql } from '~/queries/utils'

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
    actions({
        setVersionWarning: (versionWarning: SDKVersionWarning | null) => ({ versionWarning }),
    }),
    loaders({
        availableVersions: [
            null as SDKVersion[] | null,
            {
                loadAvailableVersions: async () => {
                    return await fetch('https://api.github.com/repos/posthog/posthog-js/tags')
                        .then((r) => r.json())
                        .then((r) => r.map((x: any) => ({ version: x.name.replace('v', '') })))
                },
            },
        ],
        usedVersions: [
            null as SDKVersion[] | null,
            {
                loadUsedVersions: async () => {
                    const query: HogQLQuery = {
                        kind: NodeKind.HogQLQuery,
                        query: hogql`SELECT properties.$lib_version AS lib_version, max(timestamp) AS latest_timestamp, count(lib_version) as count
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
        versionWarning: [
            null as SDKVersionWarning | null,
            // bumping cache key due to an incorrect tag being cached on 2024-02-12
            { persist: true, prefix: '2024-02-12' },
            {
                setVersionWarning: (_, { versionWarning }) => versionWarning,
            },
        ],
    }),

    sharedListeners(({ values, actions }) => ({
        checkForVersionWarning: () => {
            if (!values.availableVersions?.length || !values.usedVersions?.length) {
                return
            }

            const latestVersion = values.availableVersions[0].version

            // reverse sort, hence reversed arguments to localeCompare.
            // We want the highest semantic version to be the latest used one, rather than
            // the one with the latest timestamp, because secondary installations can spew old versions
            const latestUsedVersion = [...values.usedVersions].sort((a, b) =>
                b.version.localeCompare(a.version, undefined, { numeric: true })
            )[0].version

            if (latestVersion === latestUsedVersion) {
                actions.setVersionWarning(null)
                return
            }

            let diff = values.availableVersions.findIndex((v) => v.version === latestUsedVersion)
            diff = diff === -1 ? values.availableVersions.length : diff

            const warning: SDKVersionWarning = {
                currentVersion: latestUsedVersion,
                latestVersion,
                diff,
                level: diff > 20 ? 'error' : diff > 10 ? 'warning' : 'info',
            }

            actions.setVersionWarning(warning)
        },
    })),

    listeners(({ sharedListeners }) => ({
        loadAvailableVersionsSuccess: sharedListeners.checkForVersionWarning,
        loadUsedVersionsSuccess: sharedListeners.checkForVersionWarning,
    })),

    afterMount(({ actions, values }) => {
        if (values.lastCheckTimestamp < Date.now() - CHECK_INTERVAL_MS) {
            actions.loadAvailableVersions()
            actions.loadUsedVersions()
        }
    }),
])
