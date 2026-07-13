import { actions, connect, kea, listeners, path, reducers, selectors, sharedListeners } from 'kea'
import { forms } from 'kea-forms'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'

import { UrlTriggerConfig } from 'lib/components/IngestionControls/types'
import { compareVersion } from 'lib/utils/semver'
import { sdkHealthLogic } from 'scenes/onboarding/shared/sdkHealth/sdkHealthLogic'
import { teamLogic } from 'scenes/teamLogic'

import { TeamPublicType, TeamType } from '~/types'

import type { replayTriggersLogicType } from './replayTriggersLogicType'

export type ReplayPlatform = 'web' | 'mobile'

/** Minimum posthog-js version that understands V2 trigger groups. Older web SDKs fall back to legacy conditions. */
export const TRIGGER_GROUPS_MIN_SDK_VERSION = '1.369.0'

/**
 * Share of recent web traffic that must be on outdated SDKs before we warn / keep the legacy UI prominent.
 * Below this we treat traffic as effectively all-new, so a long tail of stray old-version events doesn't
 * raise an alarm. Lower than the backend's 20% outdated-traffic alert because trigger coverage gaps matter
 * more in this context.
 */
export const OUTDATED_TRAFFIC_SHARE_THRESHOLD = 0.05

export interface WebRelease {
    version: string
    count: number
}

const NEW_URL_TRIGGER = { url: '', matching: 'regex' }

export function isStringWithLength(x: unknown): x is string {
    return typeof x === 'string' && x.trim() !== ''
}

// Unparseable versions count as "predates" so we stay conservative (prompt upgrade / keep legacy visible).
function webSdkPredatesTriggerGroups(version: string): boolean {
    try {
        return compareVersion(version, TRIGGER_GROUPS_MIN_SDK_VERSION) < 0
    } catch {
        return true
    }
}

/**
 * Weighs recent web traffic by event volume rather than treating every distinct version equally. The SDK Doctor
 * data is a rolling ~7-day window, so this answers "how much recent traffic is on SDKs that predate trigger
 * groups". Returns zeros when there's no web data (e.g. a brand-new or self-hosted team).
 */
export function outdatedWebTrafficShare(releases: WebRelease[]): {
    outdatedCount: number
    totalCount: number
    share: number
} {
    const totalCount = releases.reduce((sum, r) => sum + r.count, 0)
    if (totalCount === 0) {
        return { outdatedCount: 0, totalCount: 0, share: 0 }
    }
    const outdatedCount = releases
        .filter((r) => webSdkPredatesTriggerGroups(r.version))
        .reduce((sum, r) => sum + r.count, 0)
    return { outdatedCount, totalCount, share: outdatedCount / totalCount }
}

/**
 * True when the team's recent web SDK traffic is effectively all on versions that understand trigger groups, so
 * the legacy recording conditions only serve a negligible tail of older SDKs. Returns false when there's no web
 * data — we never minimize the legacy UI without positive evidence.
 */
export function legacyConditionsAreInactive(releases: WebRelease[]): boolean {
    const { totalCount, share } = outdatedWebTrafficShare(releases)
    if (totalCount === 0) {
        return false
    }
    return share < OUTDATED_TRAFFIC_SHARE_THRESHOLD
}

/** True when a meaningful share of recent web traffic is on SDKs that predate trigger-group support. */
export function hasOutdatedWebSdk(releases: WebRelease[]): boolean {
    return outdatedWebTrafficShare(releases).share >= OUTDATED_TRAFFIC_SHARE_THRESHOLD
}

function ensureAnchored(url: string): string {
    url = url.startsWith('^') ? url.substring(1) : url
    url = url.endsWith('$') ? url.substring(0, url.length - 1) : url
    return `^${url}$`
}

export const replayTriggersLogic = kea<replayTriggersLogicType>([
    path(['scenes', 'settings', 'project', 'replayTriggersLogic']),
    actions({
        setUrlTriggerConfig: (urlTriggerConfig: UrlTriggerConfig[]) => ({ urlTriggerConfig }),
        addUrlTrigger: (urlTriggerConfig: UrlTriggerConfig) => ({ urlTriggerConfig }),
        removeUrlTrigger: (index: number) => ({ index }),
        updateUrlTrigger: (index: number, urlTriggerConfig: UrlTriggerConfig) => ({
            index,
            urlTriggerConfig,
        }),
        setEditUrlTriggerIndex: (originalIndex: number | null) => ({ originalIndex }),
        newUrlTrigger: true,
        cancelProposingUrlTrigger: true,

        setUrlBlocklistConfig: (urlBlocklistConfig: UrlTriggerConfig[]) => ({ urlBlocklistConfig }),
        addUrlBlocklist: (urlBlocklistConfig: UrlTriggerConfig) => ({ urlBlocklistConfig }),
        removeUrlBlocklist: (index: number) => ({ index }),
        updateUrlBlocklist: (index: number, urlBlocklistConfig: UrlTriggerConfig) => ({
            index,
            urlBlocklistConfig,
        }),
        setEditUrlBlocklistIndex: (originalIndex: number | null) => ({ originalIndex }),
        newUrlBlocklist: true,
        cancelProposingUrlBlocklist: true,
        setEventTriggerConfig: (eventTriggerConfig: string[]) => ({ eventTriggerConfig }),
        updateEventTriggerConfig: (eventTriggerConfig: string[]) => ({ eventTriggerConfig }),
        selectPlatform: (platform: ReplayPlatform) => ({ platform }),
        setCheckUrlTrigger: (url: string) => ({ url }),
        setCheckUrlBlocklist: (url: string) => ({ url }),
        validateUrlInput: (url: string, type: 'trigger' | 'blocklist') => ({ url, type }),
    }),
    connect(() => ({
        values: [teamLogic, ['currentTeam'], sdkHealthLogic, ['augmentedData']],
        actions: [teamLogic, ['updateCurrentTeam']],
    })),
    reducers({
        urlTriggerConfig: [
            null as UrlTriggerConfig[] | null,
            {
                setUrlTriggerConfig: (_, { urlTriggerConfig }) => urlTriggerConfig,
                addUrlTrigger: (state, { urlTriggerConfig }) => [...(state ?? []), urlTriggerConfig],
                updateUrlTrigger: (state, { index, urlTriggerConfig: newUrlTriggerConfig }) =>
                    (state ?? []).map((triggerConfig, i) => (i === index ? newUrlTriggerConfig : triggerConfig)),
                removeUrlTrigger: (state, { index }) => {
                    return (state ?? []).filter((_, i) => i !== index)
                },
            },
        ],
        editUrlTriggerIndex: [
            null as number | null,
            {
                setEditUrlTriggerIndex: (_, { originalIndex }) => originalIndex,
                removeUrlTrigger: (editUrlTriggerIndex, { index }) =>
                    editUrlTriggerIndex && index < editUrlTriggerIndex
                        ? editUrlTriggerIndex - 1
                        : index === editUrlTriggerIndex
                          ? null
                          : editUrlTriggerIndex,
                newUrlTrigger: () => -1,
                updateUrlTrigger: () => null,
                addUrlTrigger: () => null,
                cancelProposingUrlTrigger: () => null,
            },
        ],
        urlBlocklistConfig: [
            null as UrlTriggerConfig[] | null,
            {
                setUrlBlocklistConfig: (_, { urlBlocklistConfig }) => urlBlocklistConfig,
                addUrlBlocklist: (state, { urlBlocklistConfig }) => [...(state ?? []), urlBlocklistConfig],
                updateUrlBlocklist: (state, { index, urlBlocklistConfig: newUrlBlocklistConfig }) =>
                    (state ?? []).map((blocklistConfig, i) => (i === index ? newUrlBlocklistConfig : blocklistConfig)),
                removeUrlBlocklist: (state, { index }) => {
                    return (state ?? []).filter((_, i) => i !== index)
                },
            },
        ],
        editUrlBlocklistIndex: [
            null as number | null,
            {
                setEditUrlBlocklistIndex: (_, { originalIndex }) => originalIndex,
                removeUrlBlocklist: (editUrlBlocklistIndex, { index }) =>
                    editUrlBlocklistIndex && index < editUrlBlocklistIndex
                        ? editUrlBlocklistIndex - 1
                        : index === editUrlBlocklistIndex
                          ? null
                          : editUrlBlocklistIndex,
                newUrlBlocklist: () => -1,
                updateUrlBlocklist: () => null,
                addUrlBlocklist: () => null,
            },
        ],
        eventTriggerConfig: [
            null as string[] | null,
            {
                // we have seen some instances where a user manages to get a null into the array.
                // we guard against this by filtering out nulls, and empty strings
                // since we only want valid strings, empty arrays or null-ish, as the value here
                setEventTriggerConfig: (_, { eventTriggerConfig }) =>
                    eventTriggerConfig?.filter(isStringWithLength) ?? null,
                updateEventTriggerConfig: (_, { eventTriggerConfig }) =>
                    eventTriggerConfig?.filter(isStringWithLength) ?? null,
            },
        ],
        selectedPlatform: [
            'web' as ReplayPlatform,
            {
                selectPlatform: (_, { platform }) => platform,
            },
        ],
        checkUrlTrigger: [
            '' as string,
            {
                setCheckUrlTrigger: (_, { url }) => url,
            },
        ],
        checkUrlBlocklist: [
            '' as string,
            {
                setCheckUrlBlocklist: (_, { url }) => url,
            },
        ],
        urlTriggerInputValidationWarning: [
            null as string | null,
            {
                validateUrlInput: (_, { url, type }) => {
                    if (type !== 'trigger') {
                        return _
                    }
                    // Check if it ends with a TLD
                    if (/\.[a-z]{2,}\/?$/i.test(url)) {
                        const sanitizedUrl = url.endsWith('/') ? url.slice(0, -1) : url
                        return `If you want to match all paths of a domain, you should write " ${sanitizedUrl}(/.*)? ". This would match: 
                        ${sanitizedUrl}, ${sanitizedUrl}/, ${sanitizedUrl}/page, etc. Don't forget to include https:// at the beginning of the url.`
                    }
                    return null
                },
            },
        ],
        urlBlocklistInputValidationWarning: [
            null as string | null,
            {
                validateUrlInput: (_, { url, type }) => {
                    if (type !== 'blocklist') {
                        return _
                    }
                    // Check if it ends with a TLD
                    if (/\.[a-z]{2,}\/?$/i.test(url)) {
                        const sanitizedUrl = url.endsWith('/') ? url.slice(0, -1) : url
                        return `If you want to match all paths of a domain, you should write " ${sanitizedUrl}(/.*)? ". This would match: 
                        ${sanitizedUrl}, ${sanitizedUrl}/, ${sanitizedUrl}/page, etc. Don't forget to include https:// at the beginning of the url.`
                    }
                    return null
                },
            },
        ],
    }),
    selectors({
        shouldMinimizeLegacyConditions: [
            (s) => [s.augmentedData],
            (augmentedData): boolean => legacyConditionsAreInactive(augmentedData?.web?.allReleases ?? []),
        ],
        hasOutdatedWebSdk: [
            (s) => [s.augmentedData],
            (augmentedData): boolean => hasOutdatedWebSdk(augmentedData?.web?.allReleases ?? []),
        ],
        outdatedWebTraffic: [
            (s) => [s.augmentedData],
            (augmentedData): { outdatedCount: number; totalCount: number; share: number } =>
                outdatedWebTrafficShare(augmentedData?.web?.allReleases ?? []),
        ],
        isAddUrlTriggerConfigFormVisible: [
            (s) => [s.editUrlTriggerIndex],
            (editUrlTriggerIndex) => editUrlTriggerIndex === -1,
        ],
        urlTriggerToEdit: [
            (s) => [s.urlTriggerConfig, s.editUrlTriggerIndex],
            (urlTriggerConfig, editUrlTriggerIndex) => {
                if (
                    editUrlTriggerIndex === null ||
                    editUrlTriggerIndex === -1 ||
                    !urlTriggerConfig?.[editUrlTriggerIndex]
                ) {
                    return NEW_URL_TRIGGER
                }
                return urlTriggerConfig[editUrlTriggerIndex]
            },
        ],

        remoteUrlBlocklistConfig: [
            (s) => [s.currentTeam],
            (currentTeam) => currentTeam?.session_recording_url_blocklist_config,
        ],
        isAddUrlBlocklistConfigFormVisible: [
            (s) => [s.editUrlBlocklistIndex],
            (editUrlBlocklistIndex) => editUrlBlocklistIndex === -1,
        ],
        urlBlocklistToEdit: [
            (s) => [s.urlBlocklistConfig, s.editUrlBlocklistIndex],
            (urlBlocklistConfig, editUrlBlocklistIndex) => {
                if (
                    editUrlBlocklistIndex === null ||
                    editUrlBlocklistIndex === -1 ||
                    !urlBlocklistConfig?.[editUrlBlocklistIndex]
                ) {
                    return NEW_URL_TRIGGER
                }
                return urlBlocklistConfig[editUrlBlocklistIndex]
            },
        ],

        checkUrlTriggerResults: [
            (s) => [s.checkUrlTrigger, s.urlTriggerConfig],
            (checkUrl, urlTriggerConfig): { [key: number]: boolean } => {
                if (!checkUrl.trim() || !urlTriggerConfig) {
                    return {}
                }

                const results: { [key: number]: boolean } = {}
                urlTriggerConfig.forEach((trigger, index) => {
                    try {
                        const regex = new RegExp(trigger.url)
                        results[index] = regex.test(checkUrl)
                    } catch {
                        results[index] = false
                    }
                })
                return results
            },
        ],

        checkUrlBlocklistResults: [
            (s) => [s.checkUrlBlocklist, s.urlBlocklistConfig],
            (checkUrl, urlBlocklistConfig): { [key: number]: boolean } => {
                if (!checkUrl.trim() || !urlBlocklistConfig) {
                    return {}
                }

                const results: { [key: number]: boolean } = {}
                urlBlocklistConfig.forEach((trigger, index) => {
                    try {
                        const regex = new RegExp(trigger.url)
                        results[index] = regex.test(checkUrl)
                    } catch {
                        results[index] = false
                    }
                })
                return results
            },
        ],
    }),
    subscriptions(({ actions }) => ({
        currentTeam: (currentTeam: TeamPublicType | TeamType | null) => {
            actions.setUrlTriggerConfig(currentTeam?.session_recording_url_trigger_config ?? [])
            actions.setUrlBlocklistConfig(currentTeam?.session_recording_url_blocklist_config ?? [])
            actions.setEventTriggerConfig(
                (currentTeam?.session_recording_event_trigger_config ?? []).filter(isStringWithLength)
            )
        },
    })),
    forms(({ values, actions }) => ({
        proposedUrlTrigger: {
            defaults: { url: '', matching: 'regex' } as UrlTriggerConfig,
            errors: ({ url }) => ({
                url: !url
                    ? 'Must have a URL'
                    : (() => {
                          try {
                              new RegExp(url)
                              return undefined
                          } catch {
                              return 'Invalid regex pattern'
                          }
                      })(),
            }),
            submit: async ({ url, matching }) => {
                if (values.editUrlTriggerIndex !== null && values.editUrlTriggerIndex >= 0) {
                    actions.updateUrlTrigger(values.editUrlTriggerIndex, { url: ensureAnchored(url), matching })
                } else {
                    actions.addUrlTrigger({ url: ensureAnchored(url), matching })
                }
            },
        },
        proposedUrlBlocklist: {
            defaults: { url: '', matching: 'regex' } as UrlTriggerConfig,
            errors: ({ url }) => ({
                url: !url ? 'Must have a URL' : undefined,
            }),
            submit: async ({ url, matching }) => {
                if (values.editUrlBlocklistIndex !== null && values.editUrlBlocklistIndex >= 0) {
                    actions.updateUrlBlocklist(values.editUrlBlocklistIndex, { url: ensureAnchored(url), matching })
                } else {
                    actions.addUrlBlocklist({ url: ensureAnchored(url), matching })
                }
            },
        },
    })),
    sharedListeners(({ values }) => ({
        saveUrlTriggers: async () => {
            await teamLogic.asyncActions.updateCurrentTeam({
                session_recording_url_trigger_config: values.urlTriggerConfig ?? [],
            })
        },
        saveUrlBlocklists: async () => {
            await teamLogic.asyncActions.updateCurrentTeam({
                session_recording_url_blocklist_config: values.urlBlocklistConfig ?? [],
            })
        },
    })),
    listeners(({ sharedListeners, actions, values }) => ({
        setEditUrlTriggerIndex: () => {
            actions.setProposedUrlTriggerValue('url', values.urlTriggerToEdit.url)
            actions.setProposedUrlTriggerValue('matching', values.urlTriggerToEdit.matching)
        },
        addUrlTrigger: sharedListeners.saveUrlTriggers,
        removeUrlTrigger: sharedListeners.saveUrlTriggers,
        updateUrlTrigger: sharedListeners.saveUrlTriggers,
        submitProposedUrlTriggerSuccess: () => {
            actions.setEditUrlTriggerIndex(null)
            actions.resetProposedUrlTrigger()
        },
        setProposedUrlTriggerValue: ({ name, value }) => {
            const fieldName = Array.isArray(name) ? name[0] : name
            if (fieldName === 'url') {
                actions.validateUrlInput(value || '', 'trigger')
            }
        },

        setEditUrlBlocklistIndex: () => {
            actions.setProposedUrlBlocklistValue('url', values.urlBlocklistToEdit.url)
            actions.setProposedUrlBlocklistValue('matching', values.urlBlocklistToEdit.matching)
        },
        addUrlBlocklist: sharedListeners.saveUrlBlocklists,
        removeUrlBlocklist: sharedListeners.saveUrlBlocklists,
        updateUrlBlocklist: sharedListeners.saveUrlBlocklists,
        submitProposedUrlBlocklistSuccess: () => {
            actions.setEditUrlBlocklistIndex(null)
            actions.resetProposedUrlBlocklist()
        },
        setProposedUrlBlocklistValue: ({ name, value }) => {
            const fieldName = Array.isArray(name) ? name[0] : name
            if (fieldName === 'url') {
                actions.validateUrlInput(value || '', 'blocklist')
            }
        },
        updateEventTriggerConfig: async ({ eventTriggerConfig }) => {
            actions.setEventTriggerConfig(eventTriggerConfig)
            // ok to stringify here... this will always be a small array
            if (
                JSON.stringify(eventTriggerConfig) !==
                JSON.stringify(values.currentTeam?.session_recording_event_trigger_config)
            ) {
                await teamLogic.asyncActions.updateCurrentTeam({
                    session_recording_event_trigger_config: eventTriggerConfig,
                })
            }
        },
    })),
    actionToUrl(() => ({
        selectPlatform: ({ platform }) => {
            return [
                router.values.location.pathname,
                router.values.searchParams,
                { ...router.values.hashParams, selectedPlatform: platform },
            ]
        },
    })),
    urlToAction(({ actions, values }) => ({
        ['*/replay/settings']: (_, __, hashParams) => {
            const platformFromHash = hashParams.selectedPlatform as ReplayPlatform | undefined
            if (platformFromHash && platformFromHash !== values.selectedPlatform) {
                actions.selectPlatform(platformFromHash)
            }
        },
    })),
])
