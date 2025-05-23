import { useValues } from 'kea'
import { ErrorEventType } from 'lib/components/Errors/types'
import { Dayjs } from 'lib/dayjs'
import { useMemo } from 'react'

import { SparklineEvent } from '../components/SparklineChart/SparklineChart'
import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'

export function useSparklineEvents(): SparklineEvent<string>[] {
    const { firstSeen, firstSeenEvent, lastSeen, selectedEvent } = useValues(errorTrackingIssueSceneLogic)
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
        if (selectedEvent && !isFirstOrLastEvent(firstSeenEvent, lastSeen, selectedEvent)) {
            events.push({
                id: 'current',
                date: new Date(selectedEvent.timestamp),
                color: 'var(--brand-yellow)',
                payload: 'Current',
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
    }, [firstSeen, firstSeenEvent, lastSeen, selectedEvent])
}

function isFirstOrLastEvent(
    firstSeenEvent: ErrorEventType | null,
    lastSeen: Dayjs | null,
    selectedEvent: ErrorEventType | null
): boolean {
    if (selectedEvent && firstSeenEvent && firstSeenEvent.uuid == selectedEvent.uuid) {
        return true
    }
    if (selectedEvent && lastSeen?.isSame(selectedEvent.timestamp)) {
        return true
    }
    return false
}
