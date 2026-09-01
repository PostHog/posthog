import { Message } from 'node-rdkafka'

import { BatchBudget } from './batch-budget'
import { newPipelineBuilder } from './builders'
import { createOkContext } from './helpers'
import { isOkResult, isTimeoutResult, ok } from './results'

describe('TimeoutBarrierPipeline', () => {
    const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    type Value = { value: number }
    type Ctx = { message: Message; budget?: BatchBudget }

    /** Stands in for a step that outlasts what the batch had left. */
    function spendTheBudget() {
        jest.advanceTimersByTime(1000)
    }

    it('runs every step past the barrier once an element has crossed it', async () => {
        const ran: string[] = []
        const pipeline = newPipelineBuilder<Value, Ctx>()
            .pipe(function beforeBarrier(value: Value) {
                ran.push('beforeBarrier')
                return Promise.resolve(ok(value))
            })
            .timeoutBarrier()
            .pipe(function middleStep(value: Value) {
                ran.push('middleStep')
                // The element has already crossed, so without the barrier the
                // checkpoint would cut lastStep here.
                spendTheBudget()
                return Promise.resolve(ok(value))
            })
            .pipe(function lastStep(value: Value) {
                ran.push('lastStep')
                return Promise.resolve(ok(value))
            })
            .build()

        const budget = BatchBudget.softDeadline(Date.now() + 1000)
        const result = await pipeline.process(createOkContext({ value: 1 }, { message, budget }))

        expect(ran).toEqual(['beforeBarrier', 'middleStep', 'lastStep'])
        expect(isOkResult(result.result)).toBe(true)
        // The unlimited budget is what makes every later checkpoint a no-op.
        expect(result.context.budget).toBe(BatchBudget.unlimited())
    })

    it('cuts an element that reaches the barrier with its budget spent', async () => {
        const ran: string[] = []
        const pipeline = newPipelineBuilder<Value, Ctx>()
            .pipe(function beforeBarrier(value: Value) {
                ran.push('beforeBarrier')
                spendTheBudget()
                return Promise.resolve(ok(value))
            })
            .timeoutBarrier()
            .pipe(function afterBarrier(value: Value) {
                ran.push('afterBarrier')
                return Promise.resolve(ok(value))
            })
            .build()

        const budget = BatchBudget.softDeadline(Date.now() + 1000)
        const result = await pipeline.process(createOkContext({ value: 1 }, { message, budget }))

        expect(ran).toEqual(['beforeBarrier'])
        expect(isTimeoutResult(result.result)).toBe(true)
        expect((result.result as { reason: string }).reason).toBe('budget exceeded before timeoutBarrier')
    })

    it('passes an element through when its context carries no budget', async () => {
        const ran: string[] = []
        const pipeline = newPipelineBuilder<Value, Ctx>()
            .pipe(function beforeBarrier(value: Value) {
                ran.push('beforeBarrier')
                return Promise.resolve(ok(value))
            })
            .timeoutBarrier()
            .pipe(function afterBarrier(value: Value) {
                ran.push('afterBarrier')
                return Promise.resolve(ok(value))
            })
            .build()

        const result = await pipeline.process(createOkContext({ value: 1 }, { message }))

        expect(ran).toEqual(['beforeBarrier', 'afterBarrier'])
        expect(isOkResult(result.result)).toBe(true)
    })
})
