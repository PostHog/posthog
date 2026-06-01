import type { RecordingsQuery } from '~/queries/schema/schema-general'
import type { SessionRecordingType } from '~/types'

import { sessionReplayWidgetConfigSchema } from '../../widget_types/configSchemas'

export type SessionReplayWidgetResult = {
    results?: SessionRecordingType[]
    hasMore?: boolean
    limit?: number
}

/** Recording rows that fit in the default h:5 tile without clipping. */
export const SESSION_REPLAY_WIDGET_LOADING_SKELETON_ROW_COUNT = 4

export const SESSION_REPLAY_WIDGET_ORDER_BY_OPTIONS = [
    { value: 'start_time', label: 'Start time' },
    { value: 'activity_score', label: 'Activity score' },
    { value: 'recording_duration', label: 'Duration' },
    { value: 'click_count', label: 'Clicks' },
    { value: 'console_error_count', label: 'Console errors' },
] as const

export function getWidgetRecordingOrder(config: Record<string, unknown>): RecordingsQuery['order'] {
    const parsed = sessionReplayWidgetConfigSchema.safeParse(config)
    return parsed.success ? parsed.data.orderBy : 'start_time'
}
