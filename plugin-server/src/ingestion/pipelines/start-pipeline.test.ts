import { Message } from 'node-rdkafka'

import { dlq, drop, ok, redirect } from './results'
import { StartPipeline } from './start-pipeline'
import { StepPipeline } from './step-pipeline'

describe('StartPipeline', () => {
    describe('basic functionality', () => {
        it('should process single item through pipeline with success result', async () => {
            const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

            const pipeline = new StartPipeline<{ data: string }>().pipe((input) => {
                return ok({ processed: input.data })
            })

            const result = await pipeline.process({ result: ok({ data: 'test' }), context: { message } })
            expect(result).toEqual({ result: ok({ processed: 'test' }), context: { message } })
        })

        it('should process single item through pipeline with drop result', async () => {
            const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

            const pipeline = new StartPipeline<{ data: string }>().pipe((_input) => {
                return drop('dropped item')
            })

            const result = await pipeline.process({ result: ok({ data: 'test' }), context: { message } })
            expect(result).toEqual({ result: drop('dropped item'), context: { message } })
        })

        it('should process single item through pipeline with dlq result', async () => {
            const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

            const pipeline = new StartPipeline<{ data: string }>().pipe((_input) => {
                return dlq('dlq item', new Error('test error'))
            })

            const result = await pipeline.process({ result: ok({ data: 'test' }), context: { message } })
            expect(result).toEqual({ result: dlq('dlq item', new Error('test error')), context: { message } })
        })

        it('should process single item through pipeline with redirect result', async () => {
            const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

            const pipeline = new StartPipeline<{ data: string }>().pipe((_input) => {
                return redirect('redirect item', 'retry-topic')
            })

            const result = await pipeline.process({ result: ok({ data: 'test' }), context: { message } })
            expect(result).toEqual({ result: redirect('redirect item', 'retry-topic'), context: { message } })
        })
    })

    describe('pipe() - synchronous steps', () => {
        it('should return StepPipeline instance and call the step', async () => {
            const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message
            const step = jest.fn().mockReturnValue(ok({ processed: 'test' }))

            const pipeline = new StartPipeline<{ data: string }>()
            const stepPipeline = pipeline.pipe(step)

            expect(stepPipeline).toBeInstanceOf(StepPipeline)

            const result = await stepPipeline.process({ result: ok({ data: 'test' }), context: { message } })

            expect(step).toHaveBeenCalledWith({ data: 'test' })
            expect(result).toEqual({ result: ok({ processed: 'test' }), context: { message } })
        })
    })

    describe('pipeAsync() - async steps', () => {
        it('should return StepPipeline instance and call the async step', async () => {
            const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message
            const asyncStep = jest.fn().mockResolvedValue(ok({ processed: 'test' }))

            const pipeline = new StartPipeline<{ data: string }>()
            const stepPipeline = pipeline.pipeAsync(asyncStep)

            expect(stepPipeline).toBeInstanceOf(StepPipeline)

            const result = await stepPipeline.process({ result: ok({ data: 'test' }), context: { message } })

            expect(asyncStep).toHaveBeenCalledWith({ data: 'test' })
            expect(result).toEqual({ result: ok({ processed: 'test' }), context: { message } })
        })
    })
})
