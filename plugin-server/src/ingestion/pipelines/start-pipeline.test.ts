import { Message } from 'node-rdkafka'

import { dlq, drop, ok, redirect } from './results'
import { StartPipeline } from './start-pipeline'
import { StepPipeline } from './step-pipeline'

describe('StartPipeline', () => {
    it('should process single item through pipeline with success result', async () => {
        const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

        const pipeline = new StartPipeline<{ data: string }>().pipe((input) => {
            return Promise.resolve(ok({ processed: input.data }))
        })

        const result = await pipeline.process({ result: ok({ data: 'test' }), context: { message } })
        expect(result).toEqual({ result: ok({ processed: 'test' }), context: expect.objectContaining({ message }) })
    })

    it('should process single item through pipeline with drop result', async () => {
        const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

        const pipeline = new StartPipeline<{ data: string }>().pipe((_input) => {
            return Promise.resolve(drop('dropped item'))
        })

        const result = await pipeline.process({ result: ok({ data: 'test' }), context: { message } })
        expect(result).toEqual({ result: drop('dropped item'), context: expect.objectContaining({ message }) })
    })

    it('should process single item through pipeline with dlq result', async () => {
        const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

        const pipeline = new StartPipeline<{ data: string }>().pipe((_input) => {
            return Promise.resolve(dlq('dlq item', new Error('test error')))
        })

        const result = await pipeline.process({ result: ok({ data: 'test' }), context: { message } })
        expect(result).toEqual({
            result: dlq('dlq item', new Error('test error')),
            context: expect.objectContaining({ message }),
        })
    })

    it('should process single item through pipeline with redirect result', async () => {
        const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

        const pipeline = new StartPipeline<{ data: string }>().pipe((_input) => {
            return Promise.resolve(redirect('redirect item', 'retry-topic'))
        })

        const result = await pipeline.process({ result: ok({ data: 'test' }), context: { message } })
        expect(result).toEqual({
            result: redirect('redirect item', 'retry-topic'),
            context: expect.objectContaining({ message }),
        })
    })

    it('should return StepPipeline instance and call the async step', async () => {
        const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message
        const step = jest.fn().mockResolvedValue(ok({ processed: 'test' }))

        const pipeline = new StartPipeline<{ data: string }>()
        const stepPipeline = pipeline.pipe(step)

        expect(stepPipeline).toBeInstanceOf(StepPipeline)

        const result = await stepPipeline.process({ result: ok({ data: 'test' }), context: { message } })

        expect(step).toHaveBeenCalledWith({ data: 'test' })
        expect(result).toEqual({ result: ok({ processed: 'test' }), context: expect.objectContaining({ message }) })
    })
})
