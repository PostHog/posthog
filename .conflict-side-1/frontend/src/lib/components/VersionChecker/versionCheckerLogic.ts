import { actions, afterMount, kea, key, listeners, path, props, reducers, sharedListeners } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { isNotNil } from 'lib/utils'
import {
    SemanticVersion,
    diffVersions,
    highestVersion,
    isEqualVersion,
    parseVersion,
    tryParseVersion,
    versionToString,
} from 'lib/utils/semver'

import { hogql } from '~/queries/utils'

import type { versionCheckerLogicType } from './versionCheckerLogicType'

// If you would like to deprecate all posthog-js versions older than a specific version
// (i.e. after fixing an important bug) please edit
// https://github.com/PostHog/posthog-js/blob/main/deprecation.json

const CHECK_INTERVAL_MS = 1000 * 60 * 60 * 6 // 6 hour

export type SDKVersion = {
    version: SemanticVersion
    timestamp?: string
}

export type SDKVersionWarning = {
    latestUsedVersion: string
    latestAvailableVersion: string
    numVersionsBehind?: number
    level: 'warning' | 'info' | 'error'
}

export interface PosthogJSDeprecation {
    deprecateBeforeVersion?: string
    deprecateOlderThanDays?: number
}

export interface AvailableVersions {
    sdkVersions?: SemanticVersion[]
    deprecation?: PosthogJSDeprecation
}

export interface VersionCheckerLogicProps {
    teamId: number | null
}

export const versionCheckerLogic = kea<versionCheckerLogicType>([
    props({ teamId: null } as VersionCheckerLogicProps),
    key(({ teamId }) => teamId || 'no-team-id'),
    path((key) => ['components', 'VersionChecker', 'versionCheckerLogic', key]),
    actions({
        setVersionWarning: (versionWarning: SDKVersionWarning | null) => ({ versionWarning }),
        setSdkVersions: (sdkVersions: SDKVersion[]) => ({ sdkVersions }),
    }),
    loaders(({ values }) => ({
        availableVersions: [
            {} as AvailableVersions,
            {
                loadAvailableVersions: async (): Promise<AvailableVersions> => {
                    // Make both requests simultaneously and don't return until both have finished, to avoid a flash
                    // of partial results in the UI.
                    const availableVersionsPromise: Promise<SemanticVersion[]> = fetch(
                        'https://api.github.com/repos/posthog/posthog-js/tags'
                    )
                        .then((r) => r.json())
                        .then((r) => r.map((x: any) => tryParseVersion(x.name)).filter(isNotNil))
                    const deprecationPromise: Promise<PosthogJSDeprecation> = fetch(
                        'https://raw.githubusercontent.com/PostHog/posthog-js/main/deprecation.json'
                    ).then((r) => r.json())
                    const settled = await Promise.allSettled([availableVersionsPromise, deprecationPromise])
                    const availableVersions = settled[0].status === 'fulfilled' ? settled[0].value : []
                    const deprecation = settled[1].status === 'fulfilled' ? settled[1].value : {}
                    // if one or more of the requests failed, merge in the previous value if we have one
                    return {
                        ...values.availableVersions,
                        sdkVersions: availableVersions,
                        deprecation: deprecation,
                    }
                },
            },
        ],
        usedVersions: [
            null as SDKVersion[] | null,
            {
                loadUsedVersions: async () => {
                    const query = hogql`
                        SELECT properties.$lib_version AS lib_version, max(timestamp) AS latest_timestamp, count(lib_version) as count
                        FROM events
                        WHERE timestamp >= now() - INTERVAL 1 DAY 
                        AND timestamp <= now()
                        AND properties.$lib = 'web'
                        GROUP BY lib_version
                        ORDER BY latest_timestamp DESC
                        limit 10`

                    const res = await api.queryHogQL(query, { refresh: 'force_blocking' })

                    return (
                        res.results
                            ?.map((x) => {
                                const version = tryParseVersion(x[0])
                                if (!version) {
                                    return null
                                }
                                return {
                                    version,
                                    timestamp: x[1],
                                }
                            })
                            .filter(isNotNil) ?? null
                    )
                },
            },
        ],
    })),

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
            if (!values.usedVersions?.length) {
                return
            }
            const { deprecation, sdkVersions } = values.availableVersions

            // We want the highest semantic version to be the latest used one, rather than
            // the one with the latest timestamp, because secondary installations can spew old versions
            const latestUsedVersion = highestVersion(values.usedVersions.map((v) => v.version))

            // the latest version published on github
            const latestAvailableVersion = sdkVersions?.[0]

            // the version where, anything before this deprecated (i.e. this version is allowed, before it is not)
            const deprecateBeforeVersion = deprecation?.deprecateBeforeVersion
                ? parseVersion(deprecation.deprecateBeforeVersion)
                : null

            let warning: SDKVersionWarning | null = null

            if (deprecateBeforeVersion) {
                const diff = diffVersions(deprecateBeforeVersion, latestUsedVersion)
                // if they are behind the deprecatedBeforeVersion by any amount, show an error
                if (diff && diff.diff > 0) {
                    warning = {
                        latestUsedVersion: versionToString(latestUsedVersion),
                        latestAvailableVersion: versionToString(latestAvailableVersion || deprecateBeforeVersion),
                        level: 'error',
                    }
                }
            }

            if (!warning && sdkVersions && latestAvailableVersion) {
                const diff = diffVersions(latestAvailableVersion, latestUsedVersion)

                if (diff && diff.diff > 0) {
                    // there's a difference between the latest used version and the latest available version

                    let numVersionsBehind = sdkVersions.findIndex((v) => isEqualVersion(v, latestUsedVersion))
                    if (numVersionsBehind === -1) {
                        // if we couldn't find the versions, use the length of the list as a fallback
                        numVersionsBehind = sdkVersions.length - 1
                    }
                    if (numVersionsBehind < diff.diff) {
                        // we might have deleted versions, but if the actual diff is X then we must be at least X versions behind
                        numVersionsBehind = diff.diff
                    }

                    let level: 'warning' | 'info' | 'error' | undefined
                    if (diff.kind === 'major') {
                        level = 'info' // it is desirable to be on the latest major version, but not critical
                    } else if (diff.kind === 'minor') {
                        level = numVersionsBehind >= 40 ? 'warning' : undefined
                    }

                    if (level === undefined && numVersionsBehind >= 50) {
                        level = 'error'
                    }

                    // we check if there is a "latest user version string" to avoid returning odd data in unexpected cases
                    if (level && !!versionToString(latestUsedVersion).trim().length) {
                        warning = {
                            latestUsedVersion: versionToString(latestUsedVersion),
                            latestAvailableVersion: versionToString(latestAvailableVersion),
                            level,
                            numVersionsBehind,
                        }
                    }
                }
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
