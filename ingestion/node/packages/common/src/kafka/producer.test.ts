import { HighLevelProducer } from 'node-rdkafka'

import { KafkaProducerWrapper } from './producer'

describe('KafkaProducerWrapper.produce', () => {
    let produceMock: jest.Mock
    let wrapper: KafkaProducerWrapper

    beforeEach(() => {
        // node-rdkafka invokes the trailing (error, offset) callback; call it so produce() resolves.
        produceMock = jest.fn((...args: any[]) => {
            const cb = args[args.length - 1]
            cb(null, 0)
        })
        const mockHighLevelProducer = {
            produce: produceMock,
            on: jest.fn(),
        } as unknown as HighLevelProducer
        wrapper = new KafkaProducerWrapper(mockHighLevelProducer)
    })

    it('passes an explicit partition as the second argument to HighLevelProducer.produce', async () => {
        await wrapper.produce({ topic: 't', key: Buffer.from('k'), value: Buffer.from('v'), partition: 7 })
        expect(produceMock).toHaveBeenCalledTimes(1)
        expect(produceMock.mock.calls[0][1]).toBe(7)
    })

    it('passes null partition when none is supplied (backwards compatible)', async () => {
        await wrapper.produce({ topic: 't', key: Buffer.from('k'), value: Buffer.from('v') })
        expect(produceMock).toHaveBeenCalledTimes(1)
        expect(produceMock.mock.calls[0][1]).toBeNull()
    })

    it('treats partition 0 as explicit, not as a missing value', async () => {
        await wrapper.produce({ topic: 't', key: Buffer.from('k'), value: Buffer.from('v'), partition: 0 })
        expect(produceMock.mock.calls[0][1]).toBe(0)
    })
})
