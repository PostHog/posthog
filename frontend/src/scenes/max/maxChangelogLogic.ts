import { actions, kea, listeners, path, reducers, selectors } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { getFeatureFlagPayload } from 'lib/logic/featureFlagLogic'

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

interface AlertsPayload {
    alerts: AlertEntry[]
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

function parseAlertsPayload(payload: unknown): AlertEntry[] {
    if (!payload || typeof payload !== 'object') {
        return []
    }
    const typedPayload = payload as AlertsPayload
    if (!Array.isArray(typedPayload.alerts)) {
        return []
    }
    return typedPayload.alerts.filter(
        (alert): alert is AlertEntry =>
            typeof alert === 'object' &&
            alert !== null &&
            typeof alert.title === 'string' &&
            typeof alert.description === 'string' &&
            (alert.severity === 'warning' || alert.severity === 'error')
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

function getInitialState(): {
    entries: ChangelogEntry[]
    entriesHash: string | null
    lastSeenHash: string | null
    isDismissed: boolean
    alerts: AlertEntry[]
} {
    const payload = getFeatureFlagPayload(FEATURE_FLAGS.POSTHOG_AI_CHANGELOG)
    const entries = parseChangelogPayload(payload)
    const entriesHash = entries.length > 0 ? generateEntriesHash(entries) : null
    const lastSeenHash = getLastSeenHashFromStorage()
    const isDismissed = entriesHash ? isDismissedInStorage(entriesHash) : true

    const alertsPayload = getFeatureFlagPayload(FEATURE_FLAGS.POSTHOG_AI_ALERTS)
    const alerts = parseAlertsPayload(alertsPayload)

    return { entries, entriesHash, lastSeenHash, isDismissed, alerts }
}

export const maxChangelogLogic = kea<maxChangelogLogicType>([
    path(['scenes', 'max', 'maxChangelogLogic']),

    actions({
        openChangelog: true,
        closeChangelog: true,
        dismissChangelog: true,
        enableChangelog: true,
        setLastSeenHash: (hash: string | null) => ({ hash }),
        setIsDismissed: (isDismissed: boolean) => ({ isDismissed }),
        // For testing/storybook only
        setEntries: (entries: ChangelogEntry[]) => ({ entries }),
        setAlerts: (alerts: AlertEntry[]) => ({ alerts }),
    }),

    reducers(() => {
        const initial = getInitialState()

        return {
            entries: [
                initial.entries,
                {
                    setEntries: (_, { entries }) => entries,
                },
            ],
            entriesHash: [
                initial.entriesHash,
                {
                    setEntries: (_, { entries }) => (entries.length > 0 ? generateEntriesHash(entries) : null),
                },
            ],
            alerts: [
                initial.alerts,
                {
                    setAlerts: (_, { alerts }) => alerts,
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
                initial.lastSeenHash,
                {
                    setLastSeenHash: (_, { hash }) => hash,
                },
            ],
            isDismissed: [
                initial.isDismissed,
                {
                    setIsDismissed: (_, { isDismissed }) => isDismissed,
                    // When entries are set for testing, reset dismissed state
                    setEntries: () => false,
                },
            ],
        }
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

    selectors({
        hasEntries: [(s) => [s.entries], (entries): boolean => entries.length > 0],
        hasAlerts: [(s) => [s.alerts], (alerts): boolean => alerts.length > 0],
        hasUnread: [
            (s) => [s.entriesHash, s.lastSeenHash],
            (entriesHash, lastSeenHash): boolean => !!entriesHash && entriesHash !== lastSeenHash,
        ],
        isVisible: [
            (s) => [s.hasEntries, s.hasAlerts, s.isDismissed, s.isOpen],
            (hasEntries, hasAlerts, isDismissed, isOpen): boolean =>
                hasAlerts || (hasEntries && (!isDismissed || isOpen)),
        ],
    }),
])
