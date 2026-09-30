import { Dayjs, dayjs } from 'lib/dayjs'

import { TaskListItemApi, TaskUserBasicInfoApi } from 'products/tasks/frontend/generated/api.schemas'

/** An author counts as live while their latest session in the space had activity this recently. */
export const PRESENCE_LIVE_MINUTES = 10
/** Authors with no session activity in the space for longer than this drop out of its presence. */
export const PRESENCE_WINDOW_DAYS = 7

export interface TodaySpaceAuthor {
    user: TaskUserBasicInfoApi
    lastActivityAt: string
    live: boolean
}

/** The other people with recent sessions in each space, keyed by space id: live authors first, then most recent. */
export function spacePresence(
    sessions: TaskListItemApi[],
    currentUserId: number | null,
    now: Dayjs = dayjs()
): Record<string, TodaySpaceAuthor[]> {
    const windowStart = now.subtract(PRESENCE_WINDOW_DAYS, 'day')
    const liveStart = now.subtract(PRESENCE_LIVE_MINUTES, 'minute')
    const latest: Record<string, Map<number, TodaySpaceAuthor>> = {}
    for (const session of sessions) {
        const user = session.created_by
        const lastActivityAt = session.last_activity_at
        if (!session.channel || session.archived || !user || user.id === currentUserId || !lastActivityAt) {
            continue
        }
        const time = dayjs(lastActivityAt)
        if (time.isBefore(windowStart)) {
            continue
        }
        const authors = (latest[session.channel] ??= new Map())
        const known = authors.get(user.id)
        if (!known || time.isAfter(dayjs(known.lastActivityAt))) {
            authors.set(user.id, { user, lastActivityAt, live: !time.isBefore(liveStart) })
        }
    }
    return Object.fromEntries(
        Object.entries(latest).map(([spaceId, authors]) => [
            spaceId,
            [...authors.values()].sort(
                (first, second) =>
                    Number(second.live) - Number(first.live) ||
                    dayjs(second.lastActivityAt).valueOf() - dayjs(first.lastActivityAt).valueOf()
            ),
        ])
    )
}

export function authorName(user: Pick<TaskUserBasicInfoApi, 'first_name' | 'last_name' | 'email'>): string {
    return [user.first_name, user.last_name].filter(Boolean).join(' ') || user.email
}

export function authorInitials(name: string): string {
    return name
        .split(/\s+/)
        .slice(0, 2)
        .map((part) => part[0]?.toUpperCase())
        .join('')
}
