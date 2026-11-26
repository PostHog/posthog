import { z } from 'zod'

import { PipelineResultType, ok } from '~/ingestion/framework/results'

import { ItemResult, parseItemResults, toPipelineResults } from './service-response'

describe('service response', () => {
    const valueSchema = z.object({ id: z.number() })
    const warning = {
        type: 'error_tracking_exception_processing_errors',
        details: { errors: ['no source map'] },
        key: 'item-1',
    }

    it('parses every result kind with its warnings', () => {
        const results = [
            { result: 'ok', value: { id: 1 }, warnings: [warning] },
            { result: 'drop', reason: 'suppressed' },
            { result: 'retry', error: { code: 'deadline_exceeded', message: 'slow' } },
            { result: 'fail', error: { code: 'invalid_input', message: 'bad' } },
        ]

        expect(parseItemResults({ results }, valueSchema, 4)).toEqual(results)
    })

    it.each([
        ['a length that does not match the request', { results: [{ result: 'ok', value: { id: 1 } }] }],
        ['an unknown result kind', { results: [{ result: 'skip' }, { result: 'skip' }] }],
    ])('rejects %s as a non-retriable failure', (_case, body) => {
        expect(() => parseItemResults(body, valueSchema, 2)).toThrow(
            expect.objectContaining({ name: 'ServiceResponseError', isRetriable: false })
        )
    })

    it('turns each result into a pipeline result', () => {
        const results: ItemResult<{ id: number }>[] = [
            { result: 'ok', value: { id: 1 }, warnings: [warning] },
            { result: 'drop', reason: 'suppressed' },
            { result: 'retry', error: { code: 'deadline_exceeded', message: 'slow' } },
            { result: 'fail', error: { code: 'invalid_input', message: 'bad' } },
        ]

        const pipelineResults = toPipelineResults('svc', results, (value, index, warnings) =>
            ok({ value, index }, [], warnings)
        )

        expect(pipelineResults).toMatchObject([
            { type: PipelineResultType.OK, value: { value: { id: 1 }, index: 0 }, warnings: [warning] },
            { type: PipelineResultType.DROP, reason: 'suppressed' },
            { type: PipelineResultType.DLQ, reason: 'svc_item_retry', error: new Error('deadline_exceeded: slow') },
            { type: PipelineResultType.DLQ, reason: 'svc_item_fail', error: new Error('invalid_input: bad') },
        ])
    })

    it('skips a warning whose type is not in the registry and keeps the item', () => {
        const results: ItemResult<{ id: number }>[] = [
            { result: 'ok', value: { id: 1 }, warnings: [{ type: 'not_a_warning_type', details: {} }, warning] },
        ]

        const [result] = toPipelineResults('svc', results, (value, _index, warnings) => ok(value, [], warnings))

        expect(result).toMatchObject({ type: PipelineResultType.OK, warnings: [warning] })
    })

    it('fails the whole batch as retriable only when several items all ask for a retry', () => {
        const retry: ItemResult<{ id: number }> = {
            result: 'retry',
            error: { code: 'deadline_exceeded', message: 'slow' },
        }

        expect(() => toPipelineResults('svc', [retry, retry], (value) => ok(value))).toThrow(
            expect.objectContaining({ isRetriable: true })
        )
        expect(toPipelineResults('svc', [retry], (value) => ok(value))).toMatchObject([
            { type: PipelineResultType.DLQ, reason: 'svc_item_retry' },
        ])
    })
})
