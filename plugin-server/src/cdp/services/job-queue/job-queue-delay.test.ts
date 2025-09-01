import { Message } from 'node-rdkafka'

import { defaultConfig } from '~/config/config'

import { CyclotronJobQueueDelay, getDelayByQueue } from './job-queue-delay'

const createKafkaMessage = (message: Partial<Message> = {}): Message => ({
    value: Buffer.from('test-value'),
    key: Buffer.from('test-key'),
    offset: 1,
    partition: 0,
    topic: 'cdp_cyclotron_delay_10m',
    size: 10,
    headers: [],
    ...message,
})

const createHeaders = (headers: Record<string, string>): any[] =>
    Object.entries(headers).map(([k, v]) => ({ [k]: Buffer.from(v, 'utf8') }))

describe('CyclotronJobQueueDelay', () => {
    let queue: CyclotronJobQueueDelay
    let mockProducer: { produce: jest.Mock }
    let mockConsumer: { offsetsStore: jest.Mock }
    let consumeBatch: jest.Mock

    beforeEach(() => {
        jest.useFakeTimers()
        consumeBatch = jest.fn().mockResolvedValue({ backgroundTask: Promise.resolve() })
        queue = new CyclotronJobQueueDelay({ ...defaultConfig }, 'delay_10m', consumeBatch)
        queue['kafkaProducer'] = (mockProducer = { produce: jest.fn().mockResolvedValue(undefined) }) as any
        queue['kafkaConsumer'] = mockConsumer = { offsetsStore: jest.fn() } as any
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('routes immediately to returnTopic when scheduled in the past', async () => {
        const headers = createHeaders({
            returnTopic: 'cdp_cyclotron_hog',
            queueScheduledAt: new Date(Date.now() - 1000).toISOString(),
        })
        const msg = createKafkaMessage({ headers })

        const p = (queue as any)['consumeKafkaBatch']([msg])
        await Promise.resolve()
        jest.advanceTimersByTime(0)
        await p

        expect(mockProducer.produce).toHaveBeenCalledWith(
            expect.objectContaining({
                value: msg.value,
                key: msg.key as any,
                topic: 'cdp_cyclotron_hog',
                headers: headers as any,
            })
        )
        expect(mockConsumer.offsetsStore).toHaveBeenCalledWith([msg])
        expect(consumeBatch).toHaveBeenCalledWith([])
    })

    it('waits up to scheduled time (short wait) then routes to returnTopic', async () => {
        const waitMs = 5000
        const headers = createHeaders({
            returnTopic: 'cdp_cyclotron_hog',
            queueScheduledAt: new Date(Date.now() + waitMs).toISOString(),
        })
        const msg = createKafkaMessage({ headers })

        const promise = (queue as any)['consumeKafkaBatch']([msg])
        jest.advanceTimersByTime(waitMs)
        await Promise.resolve()
        await promise

        expect(mockProducer.produce).toHaveBeenCalledWith(expect.objectContaining({ topic: 'cdp_cyclotron_hog' }))
        expect(mockConsumer.offsetsStore).toHaveBeenCalledWith([msg])
    })

    it('caps wait at 10m and re-queues to delay topic when still in the future', async () => {
        const longMs = getDelayByQueue('delay_10m') * 3
        const tenMinutes = getDelayByQueue('delay_10m')
        const headers = createHeaders({
            returnTopic: 'cdp_cyclotron_hog',
            queueScheduledAt: new Date(Date.now() + longMs).toISOString(),
        })
        const msg = createKafkaMessage({ headers })

        const promise = (queue as any)['consumeKafkaBatch']([msg])
        jest.advanceTimersByTime(tenMinutes)
        await Promise.resolve()
        await promise

        expect(mockProducer.produce).toHaveBeenCalledWith(
            expect.objectContaining({
                topic: 'cdp_cyclotron_delay_10m',
            })
        )
        expect(mockConsumer.offsetsStore).toHaveBeenCalledWith([msg])
    })

    it('skips message and commits offset when required headers are missing', async () => {
        const msgNoHeaders = createKafkaMessage({ headers: [] })

        await (queue as any)['consumeKafkaBatch']([msgNoHeaders])

        expect(mockProducer.produce).not.toHaveBeenCalled()
        expect(mockConsumer.offsetsStore).toHaveBeenCalledWith([msgNoHeaders])
    })
})
