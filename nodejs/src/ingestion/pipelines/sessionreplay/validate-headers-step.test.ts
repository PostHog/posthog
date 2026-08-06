import { PipelineResultType, isOkResult } from '~/ingestion/framework/results'
import { createTestEventHeaders } from '~/tests/helpers/event-headers'
import { EventHeaders } from '~/types'

import { createValidateSessionReplayHeadersStep } from './validate-headers-step'

describe('createValidateSessionReplayHeadersStep', () => {
    const step = createValidateSessionReplayHeadersStep()

    it('narrows headers to the guaranteed fields and drops the rest, preserving other input', async () => {
        const step = createValidateSessionReplayHeadersStep<{ marker: string; headers: EventHeaders }>()
        const input = {
            marker: 'preserved',
            headers: createTestEventHeaders({ token: 'tok', session_id: 'sess-1', distinct_id: 'user-1' }),
        }

        const result = await step(input)

        expect(isOkResult(result)).toBe(true)
        if (isOkResult(result)) {
            expect(result.value.marker).toBe('preserved')
            // Only the guaranteed replay headers survive — the wide EventHeaders fields are dropped.
            expect(result.value.headers).toEqual({ token: 'tok', session_id: 'sess-1', distinct_id: 'user-1' })
        }
    })

    it('normalizes a UUID session_id to its canonical (lowercase) form', async () => {
        const result = await step({
            headers: createTestEventHeaders({
                token: 'tok',
                session_id: '0192E72A-1DD2-7714-8000-8B3E4C123456',
                distinct_id: 'user-1',
            }),
        })

        expect(isOkResult(result)).toBe(true)
        if (isOkResult(result)) {
            expect(result.value.headers.session_id).toBe('0192e72a-1dd2-7714-8000-8b3e4c123456')
        }
    })

    // Capture guarantees all three headers, so a missing one is an upstream bug → DLQ.
    it.each([
        { missing: 'token', headers: { session_id: 'sess-1', distinct_id: 'user-1' }, reason: 'no_token_in_header' },
        { missing: 'session_id', headers: { token: 'tok', distinct_id: 'user-1' }, reason: 'no_session_id_in_header' },
        { missing: 'distinct_id', headers: { token: 'tok', session_id: 'sess-1' }, reason: 'no_distinct_id_in_header' },
    ])('DLQs when the $missing header is missing', async ({ headers, reason }) => {
        const result = await step({ headers: createTestEventHeaders(headers) })

        expect(result.type).toBe(PipelineResultType.DLQ)
        if (result.type === PipelineResultType.DLQ) {
            expect(result.reason).toBe(reason)
        }
    })
})
