import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { incidentStatusLogic } from 'lib/components/HelpMenu/incidentStatusLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic, getFeatureFlagPayload } from 'lib/logic/featureFlagLogic'

import type { maxChangelogLogicType } from './maxChangelogLogicType'

export interface ChangelogEntry {
    title: string
    description: string
    tag?: 'new' | 'improved' | 'beta'
}

export interface AlertEntry {
    title: string
    description: string
    severity: 'warning' | 'error'
}

interface ChangelogPayload {
    entries: ChangelogEntry[]
}

const CHANGELOG_STORAGE_KEY = 'posthog_ai_changelog_last_seen'
const CHANGELOG_DISMISSED_KEY = 'posthog_ai_changelog_dismissed'

function generateEntriesHash(entries: ChangelogEntry[]): string {
    const content = entries.map((e) => `${e.title}|${e.description}|${e.tag || ''}`).join('::')
    let hash = 0
    for (let i = 0; i < content.length; i++) {
        const char = content.charCodeAt(i)
        hash = (hash << 5) - hash + char
        hash = hash & hash
    }
    return Math.abs(hash).toString(36)
}

function parseChangelogPayload(payload: unknown): ChangelogEntry[] {
    if (!payload || typeof payload !== 'object') {
        return []
    }
    const typedPayload = payload as ChangelogPayload
    if (!Array.isArray(typedPayload.entries)) {
        return []
    }
    return typedPayload.entries.filter(
        (entry): entry is ChangelogEntry =>
            typeof entry === 'object' &&
            entry !== null &&
            typeof entry.title === 'string' &&
            typeof entry.description === 'string'
    )
}

function getLastSeenHashFromStorage(): string | null {
    try {
        return localStorage.getItem(CHANGELOG_STORAGE_KEY)
    } catch {
        return null
    }
}

function setLastSeenHashToStorage(hash: string): void {
    try {
        localStorage.setItem(CHANGELOG_STORAGE_KEY, hash)
    } catch {
        // Ignore storage errors
    }
}

function isDismissedInStorage(hash: string): boolean {
    try {
        const dismissedHash = localStorage.getItem(CHANGELOG_DISMISSED_KEY)
        return dismissedHash === hash
    } catch {
        return false
    }
}

function setDismissedInStorage(hash: string): void {
    try {
        localStorage.setItem(CHANGELOG_DISMISSED_KEY, hash)
    } catch {
        // Ignore storage errors
    }
}

function clearDismissedFromStorage(): void {
    try {
        localStorage.removeItem(CHANGELOG_DISMISSED_KEY)
    } catch {
        // Ignore storage errors
    }
}

export const maxChangelogLogic = kea<maxChangelogLogicType>([
    path(['scenes', 'max', 'maxChangelogLogic']),

    connect(() => ({
        values: [featureFlagLogic, ['featureFlags'], incidentStatusLogic, ['aiIncidentAlerts']],
    })),

    actions({
        openChangelog: true,
        closeChangelog: true,
        dismissChangelog: true,
        enableChangelog: true,
        setLastSeenHash: (hash: string | null) => ({ hash }),
        setIsDismissed: (isDismissed: boolean) => ({ isDismissed }),
        // For testing/storybook only
        setEntries: (entries: ChangelogEntry[]) => ({ entries }),
    }),

    reducers({
        // Override entries for testing - null means use feature flag payload
        entriesOverride: [
            null as ChangelogEntry[] | null,
            {
                setEntries: (_, { entries }) => entries,
            },
        ],
        isOpen: [
            false,
            {
                openChangelog: () => true,
                closeChangelog: () => false,
                dismissChangelog: () => false,
            },
        ],
        lastSeenHash: [
            getLastSeenHashFromStorage(),
            {
                setLastSeenHash: (_, { hash }) => hash,
            },
        ],
        isDismissedOverride: [
            null as boolean | null,
            {
                setIsDismissed: (_, { isDismissed }) => isDismissed,
                // When entries are set for testing, reset dismissed state
                setEntries: () => false,
            },
        ],
    }),

    selectors({
        // Derive entries from feature flag payload, with override for testing
        entries: [
            (s) => [s.entriesOverride, s.featureFlags],
            (entriesOverride, featureFlags): ChangelogEntry[] => {
                if (entriesOverride !== null) {
                    return entriesOverride
                }
                // featureFlags dependency ensures this re-runs when flags load
                if (!featureFlags) {
                    return []
                }
                const payload = getFeatureFlagPayload(FEATURE_FLAGS.POSTHOG_AI_CHANGELOG)
                return parseChangelogPayload(payload)
            },
        ],
        // Derive alerts from ongoing incident.io incidents tagged to PostHog AI
        alerts: [(s) => [s.aiIncidentAlerts], (aiIncidentAlerts): AlertEntry[] => aiIncidentAlerts],
        entriesHash: [
            (s) => [s.entries],
            (entries): string | null => (entries.length > 0 ? generateEntriesHash(entries) : null),
        ],
        hasEntries: [(s) => [s.entries], (entries): boolean => entries.length > 0],
        hasAlerts: [(s) => [s.alerts], (alerts): boolean => alerts.length > 0],
        hasUnread: [
            (s) => [s.entriesHash, s.lastSeenHash],
            (entriesHash, lastSeenHash): boolean => !!entriesHash && entriesHash !== lastSeenHash,
        ],
        isDismissed: [
            (s) => [s.isDismissedOverride, s.entriesHash],
            (isDismissedOverride, entriesHash): boolean => {
                if (isDismissedOverride !== null) {
                    return isDismissedOverride
                }
                return entriesHash ? isDismissedInStorage(entriesHash) : true
            },
        ],
        isVisible: [
            (s) => [s.hasEntries, s.hasAlerts, s.isDismissed, s.isOpen],
            (hasEntries, hasAlerts, isDismissed, isOpen): boolean =>
                hasAlerts || (hasEntries && (!isDismissed || isOpen)),
        ],
    }),

    listeners(({ actions, values }) => ({
        openChangelog: () => {
            if (values.entriesHash) {
                setLastSeenHashToStorage(values.entriesHash)
                actions.setLastSeenHash(values.entriesHash)
            }
        },
        dismissChangelog: () => {
            if (values.entriesHash) {
                setDismissedInStorage(values.entriesHash)
            }
            actions.setIsDismissed(true)
        },
        enableChangelog: () => {
            clearDismissedFromStorage()
            actions.setIsDismissed(false)
        },
    })),
])
