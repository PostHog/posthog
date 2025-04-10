import { useValues } from 'kea'
import { useMemo } from 'react'

import { SparklineEvent } from '../components/SparklineChart/SparklineChart'
import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'

export function useSparklineEvents(): SparklineEvent<string>[] {
    const { firstSeen, lastSeen } = useValues(errorTrackingIssueSceneLogic)
    return useMemo(() => {
        const events = []
        if (firstSeen) {
            events.push({
                id: 'first_seen',
                date: firstSeen.toDate(),
                color: 'var(--brand-blue)',
                payload: 'First Seen',
                radius: 6,
            })
        }
        if (lastSeen) {
            events.push({
                id: 'last_seen',
                date: lastSeen.toDate(),
                color: 'var(--brand-red)',
                payload: 'Last Seen',
                radius: 6,
            })
        }
        return events
    }, [firstSeen, lastSeen])
}
