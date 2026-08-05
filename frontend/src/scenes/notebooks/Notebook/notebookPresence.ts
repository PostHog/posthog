import { uuid } from 'lib/utils/dom'

import type { UserType } from '~/types'

const NOTEBOOK_MARKDOWN_CLIENT_ID_SESSION_STORAGE_KEY = 'posthog_notebook_markdown_client_id'

export type NotebookPresenceState = {
    clientId: string
    userId: number
    userName: string
    lastSeenAt: number
}

export type NotebookRemoteParticipant = NotebookPresenceState

export type NotebookPresenceParticipant = NotebookPresenceState & {
    isCurrentUser?: boolean
    isAI?: boolean
    profileUser?: Pick<UserType, 'email' | 'first_name' | 'hedgehog_config'>
}

export const NOTEBOOK_AI_PRESENCE_CLIENT_ID = 'notebook-agent:ai'
export const NOTEBOOK_AI_PRESENCE_USER_ID = 100_185
export const NOTEBOOK_AI_PRESENCE_NAME = 'AI'
export const NOTEBOOK_AI_PRESENCE_COLOR = 'var(--color-text-success)'

export function getNotebookRemoteParticipants<T extends NotebookPresenceState>(
    presenceByClientId: Record<string, T>
): NotebookRemoteParticipant[] {
    const latestPresenceByUserId = new Map<number, T>()

    for (const presence of Object.values(presenceByClientId)) {
        const currentPresence = latestPresenceByUserId.get(presence.userId)
        if (!currentPresence || presence.lastSeenAt > currentPresence.lastSeenAt) {
            latestPresenceByUserId.set(presence.userId, presence)
        }
    }

    return Array.from(latestPresenceByUserId.values())
        .sort((a, b) => a.userName.localeCompare(b.userName) || a.userId - b.userId)
        .map((presence) => ({ ...presence }))
}

export function getNotebookPresenceParticipants(
    currentUser: Pick<UserType, 'email' | 'first_name' | 'hedgehog_config' | 'id'> | null,
    remoteParticipants: NotebookRemoteParticipant[],
    now: number = Date.now()
): NotebookPresenceParticipant[] {
    if (!currentUser) {
        return remoteParticipants
    }

    return [
        {
            clientId: 'current-user',
            userId: currentUser.id,
            userName: 'You',
            lastSeenAt: now,
            isCurrentUser: true,
            profileUser: currentUser,
        },
        ...remoteParticipants.filter((participant) => participant.userId !== currentUser.id),
    ]
}

export function pruneNotebookRemotePresence<T extends NotebookPresenceState>(
    presenceByClientId: Record<string, T>,
    now: number,
    ttlMs: number
): Record<string, T> {
    const freshPresence = Object.entries(presenceByClientId).filter(
        ([, presence]) => now - presence.lastSeenAt <= ttlMs
    )
    return freshPresence.length === Object.keys(presenceByClientId).length
        ? presenceByClientId
        : (Object.fromEntries(freshPresence) as Record<string, T>)
}

export function getNotebookMarkdownClientId(): string {
    const nextClientId = uuid()
    if (typeof window === 'undefined') {
        return nextClientId
    }

    try {
        const storedClientId = window.sessionStorage.getItem(NOTEBOOK_MARKDOWN_CLIENT_ID_SESSION_STORAGE_KEY)
        if (storedClientId && getNavigationType() === 'reload') {
            return storedClientId
        }
        window.sessionStorage.setItem(NOTEBOOK_MARKDOWN_CLIENT_ID_SESSION_STORAGE_KEY, nextClientId)
    } catch {
        // Storage can be unavailable in private or embedded contexts. Presence is best effort.
    }

    return nextClientId
}

function getNavigationType(): PerformanceNavigationTiming['type'] | null {
    if (typeof window.performance?.getEntriesByType !== 'function') {
        return null
    }

    const navigation = window.performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined
    if (!navigation || !navigation.type) {
        return null
    }
    return navigation.type
}
