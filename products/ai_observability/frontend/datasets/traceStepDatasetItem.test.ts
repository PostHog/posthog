import type { TraceNodeDatasetItemApi } from '../generated/api.schemas'
import { toDatasetItemDraft } from './traceStepDatasetItem'

describe('toDatasetItemDraft', () => {
    const item: TraceNodeDatasetItemApi = {
        clientItemId: 'event-1',
        sourceTraceId: 'trace-1',
        sourceEventId: 'event-1',
        sourceTimestamp: '2026-11-11T10:00:00Z',
        input: [{ toolCalls: [{ id: 'c1' }] }],
        sourceOutput: { content: 'hi' },
        metadata: { finishReason: 'stop' },
    }

    it('maps every field to the create payload shape and leaves payload keys alone', () => {
        expect(toDatasetItemDraft(item)).toEqual({
            client_item_id: 'event-1',
            source_trace_id: 'trace-1',
            source_event_id: 'event-1',
            source_timestamp: '2026-11-11T10:00:00Z',
            input: [{ toolCalls: [{ id: 'c1' }] }],
            source_output: { content: 'hi' },
            metadata: { finishReason: 'stop' },
        })
    })
})
