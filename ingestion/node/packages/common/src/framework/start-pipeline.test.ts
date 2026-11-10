import { Message } from 'node-rdkafka'

import { createContext, createOkContext } from './helpers'
import { dlq, drop, ok, redirect } from './results'
import { StartPipeline } from './start-pipeline'
import { StepPipeline } from './step-pipeline'

const TEST_REDIRECT_OUTPUT = 'test_redirect' as const

describe('StartPipeline', () => {
    it('should process single item through pipeline with success result', async () => {
        const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

        const pipeline = new StartPipeline<{ data: string }, unknown>().pipe((input) => {
            return Promise.resolve(ok({ processed: input.data }))
        })

        const result = await pipeline.process(createOkContext({ data: 'test' }, { message }))
        expect(result).toEqual(createContext(ok({ processed: 'test' }), { message, lastStep: 'anonymousStep' }))
    })

    it('should process single item through pipeline with drop result', async () => {
        const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

        const pipeline = new StartPipeline<{ data: string }, unknown>().pipe((_input) => {
            return Promise.resolve(drop('dropped item'))
        })

        const result = await pipeline.process(createOkContext({ data: 'test' }, { message }))
        expect(result).toEqual(createContext(drop('dropped item'), { message, lastStep: 'anonymousStep' }))
    })

    it('should process single item through pipeline with dlq result', async () => {
        const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

        const pipeline = new StartPipeline<{ data: string }, unknown>().pipe((_input) => {
            return Promise.resolve(dlq('dlq item', new Error('test error')))
        })

        const result = await pipeline.process(createOkContext({ data: 'test' }, { message }))
        expect(result).toEqual(
            createContext(dlq('dlq item', new Error('test error')), { message, lastStep: 'anonymousStep' })
        )
    })

    it('should process single item through pipeline with redirect result', async () => {
        const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message

        const pipeline = new StartPipeline<{ data: string }, unknown>().pipe((_input) => {
            return Promise.resolve(redirect('redirect item', TEST_REDIRECT_OUTPUT))
        })

        const result = await pipeline.process(createOkContext({ data: 'test' }, { message }))
        expect(result).toEqual(
            createContext(redirect('redirect item', TEST_REDIRECT_OUTPUT), { message, lastStep: 'anonymousStep' })
        )
    })

    it('should return StepPipeline instance and call the async step', async () => {
        const message: Message = { value: Buffer.from('test'), topic: 'test', partition: 0, offset: 1 } as Message
        const step = jest.fn().mockResolvedValue(ok({ processed: 'test' }))

        const pipeline = new StartPipeline<{ data: string }, unknown>()
        const stepPipeline = pipeline.pipe(step)

        expect(stepPipeline).toBeInstanceOf(StepPipeline)

        const result = await stepPipeline.process(createOkContext({ data: 'test' }, { message }))

        expect(step).toHaveBeenCalledWith({ data: 'test' })
        expect(result).toEqual(createContext(ok({ processed: 'test' }), { message, lastStep: 'mockConstructor' }))
    })
})
