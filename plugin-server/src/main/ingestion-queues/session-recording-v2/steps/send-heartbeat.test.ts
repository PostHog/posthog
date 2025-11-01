import { ok } from '../../../../ingestion/pipelines/results'
import { KafkaConsumer } from '../../../../kafka/consumer'
import { createSendHeartbeatStep } from './send-heartbeat'

describe('send-heartbeat', () => {
    const mockKafkaConsumer = {
        heartbeat: jest.fn(),
    } as unknown as KafkaConsumer

    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('should send heartbeat and pass through input', async () => {
        const input = [{ data: 'test1' }, { data: 'test2' }]
        const step = createSendHeartbeatStep(mockKafkaConsumer)
        const result = await step(input)

        expect(mockKafkaConsumer.heartbeat).toHaveBeenCalledTimes(1)
        expect(result).toEqual([ok({ data: 'test1' }), ok({ data: 'test2' })])
    })

    it('should pass through empty batch', async () => {
        const step = createSendHeartbeatStep(mockKafkaConsumer)
        const result = await step([])

        expect(mockKafkaConsumer.heartbeat).toHaveBeenCalledTimes(1)
        expect(result).toEqual([])
    })

    it('should work with any input type', async () => {
        const input = [1, 2, 3]
        const step = createSendHeartbeatStep(mockKafkaConsumer)
        const result = await step(input)

        expect(mockKafkaConsumer.heartbeat).toHaveBeenCalledTimes(1)
        expect(result).toEqual([ok(1), ok(2), ok(3)])
    })

    it('should send heartbeat even with void input', async () => {
        const input = [undefined, undefined]
        const step = createSendHeartbeatStep(mockKafkaConsumer)
        const result = await step(input)

        expect(mockKafkaConsumer.heartbeat).toHaveBeenCalledTimes(1)
        expect(result).toEqual([ok(undefined), ok(undefined)])
    })
})
