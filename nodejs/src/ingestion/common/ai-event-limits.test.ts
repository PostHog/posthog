import { readFileSync } from 'fs'
import path from 'path'

import { parseJSON } from '~/common/utils/json-parse'

import { AI_INCLUDED_BYTES_PER_EVENT, AI_MAX_EVENT_BYTES_CEILING, AI_MEDIA_OFFLOAD_MIN_BYTES } from './ai-event-limits'

const LIMITS_JSON = path.resolve(
    __dirname,
    '../../../../products/ai_observability/shared/crosslang/ai_event_limits.json'
)

describe('ai-event-limits', () => {
    it('mirrors products/ai_observability/shared/crosslang/ai_event_limits.json', () => {
        const limits = parseJSON(readFileSync(LIMITS_JSON, 'utf8'))

        expect({
            max_event_bytes_ceiling: AI_MAX_EVENT_BYTES_CEILING,
            included_bytes_per_event: AI_INCLUDED_BYTES_PER_EVENT,
            media_offload_min_bytes: AI_MEDIA_OFFLOAD_MIN_BYTES,
        }).toEqual({
            max_event_bytes_ceiling: limits.max_event_bytes_ceiling,
            included_bytes_per_event: limits.included_bytes_per_event,
            media_offload_min_bytes: limits.media_offload_min_bytes,
        })
    })
})
