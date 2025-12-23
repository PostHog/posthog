import { WorkerResult, WorkerResultType } from './serializable'

describe('serializable types', () => {
    describe('WorkerResultType', () => {
        it('should have correct enum values', () => {
            expect(WorkerResultType.OK).toBe(0)
            expect(WorkerResultType.DLQ).toBe(1)
            expect(WorkerResultType.DROP).toBe(2)
            expect(WorkerResultType.REDIRECT).toBe(3)
        })
    })

    describe('WorkerResult', () => {
        it('should create OK result', () => {
            const result: WorkerResult = {
                type: WorkerResultType.OK,
                correlationId: 'test-id',
                value: Buffer.from('test'),
                warnings: [],
            }
            expect(result.type).toBe(WorkerResultType.OK)
            expect(result.correlationId).toBe('test-id')
        })

        it('should create DLQ result', () => {
            const result: WorkerResult = {
                type: WorkerResultType.DLQ,
                correlationId: 'test-id',
                reason: 'test error',
                error: 'Error details',
                warnings: [{ type: 'test', details: {} }],
            }
            expect(result.type).toBe(WorkerResultType.DLQ)
            expect(result.reason).toBe('test error')
        })

        it('should create DROP result', () => {
            const result: WorkerResult = {
                type: WorkerResultType.DROP,
                correlationId: 'test-id',
                reason: 'dropped',
                warnings: [],
            }
            expect(result.type).toBe(WorkerResultType.DROP)
        })

        it('should create REDIRECT result', () => {
            const result: WorkerResult = {
                type: WorkerResultType.REDIRECT,
                correlationId: 'test-id',
                reason: 'redirect reason',
                topic: 'target-topic',
                preserveKey: true,
                awaitAck: false,
                warnings: [],
            }
            expect(result.type).toBe(WorkerResultType.REDIRECT)
            expect(result.topic).toBe('target-topic')
        })
    })
})
