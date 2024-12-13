import { dayjs } from 'lib/dayjs'

import { ErrorTrackingIssue } from '~/queries/schema'

export const mergeIssues = (
    primaryIssue: ErrorTrackingIssue,
    mergingIssues: ErrorTrackingIssue[]
): ErrorTrackingIssue => {
    const sum = (value: 'occurrences' | 'users' | 'sessions'): number => {
        return mergingIssues.reduce((sum, g) => sum + g[value], primaryIssue[value])
    }

    const [firstSeen, lastSeen] = mergingIssues.reduce(
        (res, g) => {
            const firstSeen = dayjs(g.first_seen)
            const lastSeen = dayjs(g.last_seen)
            return [res[0].isAfter(firstSeen) ? firstSeen : res[0], res[1].isBefore(lastSeen) ? lastSeen : res[1]]
        },
        [dayjs(primaryIssue.first_seen), dayjs(primaryIssue.last_seen)]
    )

    const volume = primaryIssue.volume

    if (volume) {
        const dataIndex = 3
        const data = mergingIssues.reduce(
            (sum: number[], g) => g.volume[dataIndex].map((num: number, idx: number) => num + sum[idx]),
            primaryIssue.volume[dataIndex]
        )
        volume.splice(dataIndex, 1, data)
    }

    return {
        ...primaryIssue,
        occurrences: sum('occurrences'),
        sessions: sum('sessions'),
        users: sum('users'),
        first_seen: firstSeen.toISOString(),
        last_seen: lastSeen.toISOString(),
        volume: volume,
    }
}
