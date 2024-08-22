import { dayjs } from 'lib/dayjs'
import { base64Encode } from 'lib/utils'

import { ErrorTrackingGroup } from '~/queries/schema'

export const mergeGroups = (
    primaryGroup: ErrorTrackingGroup,
    mergingGroups: ErrorTrackingGroup[]
): ErrorTrackingGroup => {
    const mergingFingerprints = mergingGroups.flatMap((g) => [g.fingerprint, ...g.merged_fingerprints])

    const mergedFingerprints = [...primaryGroup.merged_fingerprints]
    mergedFingerprints.push(...mergingFingerprints)

    const sum = (value: 'occurrences' | 'users' | 'sessions'): number => {
        return mergingGroups.reduce((sum, g) => sum + g[value], primaryGroup[value])
    }

    const [firstSeen, lastSeen] = mergingGroups.reduce(
        (res, g) => {
            const firstSeen = dayjs(g.first_seen)
            const lastSeen = dayjs(g.last_seen)
            return [res[0].isAfter(firstSeen) ? firstSeen : res[0], res[1].isBefore(lastSeen) ? lastSeen : res[1]]
        },
        [dayjs(primaryGroup.first_seen), dayjs(primaryGroup.last_seen)]
    )

    const volume = primaryGroup.volume

    if (volume) {
        const dataIndex = 3
        const data = mergingGroups.reduce(
            (sum: number[], g) => g.volume[dataIndex].map((num: number, idx: number) => num + sum[idx]),
            primaryGroup.volume[dataIndex]
        )
        volume.splice(dataIndex, 1, data)
    }

    return {
        ...primaryGroup,
        merged_fingerprints: mergedFingerprints,
        occurrences: sum('occurrences'),
        sessions: sum('sessions'),
        users: sum('users'),
        first_seen: firstSeen.toISOString(),
        last_seen: lastSeen.toISOString(),
        volume: volume,
    }
}

export const stringifiedFingerprint = (fingerprint: string[]): string => {
    return base64Encode(JSON.stringify(fingerprint))
}
