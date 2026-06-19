import type { UserType } from '~/types'

export type NotebookPresenceState = {
    clientId: string
    userId: number
    userName: string
    lastSeenAt: number
}

export type NotebookRemoteParticipant = NotebookPresenceState

export type NotebookPresenceParticipant = NotebookPresenceState & {
    isCurrentUser?: boolean
    profileUser?: Pick<UserType, 'email' | 'first_name' | 'hedgehog_config'>
}

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
