import { ApiConfig } from 'lib/api'
import { dayjs } from 'lib/dayjs'

import { aiObservabilitySessionsRetrieve } from '../../generated/api'
import type { SessionListItemApi } from '../../generated/api.schemas'
import { parseUrlDate } from '../shared/parseUrlDate'
import { readOrFailure } from '../shared/readOrFailure'
import { encodeTraceIdSegment } from '../trace/traceIdSegment'
import type { LoadFailure } from '../trace/types'

// A session started in the past, so a later time is a broken link. Allow for a clock that runs a little ahead.
const LATEST_HINT_AHEAD_DAYS = 1

/**
 * The time a session link carries, in the form the read accepts, or null when the link's text is no usable time. The
 * read refuses a time it cannot parse or place, so a broken one is dropped rather than failing every read of the link.
 */
export function sessionTimestampHint(raw: string | null): string | null {
    const parsed = raw ? parseUrlDate(raw) : null
    if (!parsed) {
        return null
    }
    const hint = dayjs(parsed)
    const latest = dayjs().add(LATEST_HINT_AHEAD_DAYS, 'day')
    return hint.isAfter(latest) || hint.isBefore(dayjs(0)) ? null : hint.toISOString()
}

export function readSession(
    sessionId: string,
    rawTimestamp: string | null
): Promise<{ value: SessionListItemApi } | { failure: LoadFailure }> {
    const timestamp = sessionTimestampHint(rawTimestamp)
    return readOrFailure(
        aiObservabilitySessionsRetrieve(
            String(ApiConfig.getCurrentProjectId()),
            encodeTraceIdSegment(sessionId),
            timestamp ? { timestamp } : undefined
        )
    )
}
