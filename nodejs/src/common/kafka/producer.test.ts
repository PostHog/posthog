import { HighLevelProducer } from 'node-rdkafka'

import { UnknownTopicError } from '../utils/db/error'
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

    // A missing topic reaches the delivery callback in more than one shape. Broker code 3 and local
    // code -188 are the documented ones, but a broker that answers the metadata request slowly
    // enough reports it with code -1 and only the librdkafka text. All three have to classify as
    // unroutable, because the caller drops those jobs instead of retrying the batch forever.
    it.each([
        ['broker code', { code: 3, message: 'Broker: Unknown topic or partition' }],
        ['local code', { code: -188, message: 'Local: Unknown topic' }],
        ['code-less delivery report', { code: -1, message: 'unknown topic or partition' }],
    ])('reports an absent topic as unroutable: %s', async (_label, error) => {
        produceMock.mockImplementation((...args: any[]) => args[args.length - 1](error, null))

        await expect(
            wrapper.produce({ topic: 'cdp_cyclotron_email', key: null, value: Buffer.from('v') })
        ).rejects.toBeInstanceOf(UnknownTopicError)
    })

    it('leaves an unrelated produce failure as it is', async () => {
        produceMock.mockImplementation((...args: any[]) =>
            args[args.length - 1]({ code: 7, message: 'Broker: Request timed out' }, null)
        )

        await expect(wrapper.produce({ topic: 't', key: null, value: Buffer.from('v') })).rejects.not.toBeInstanceOf(
            UnknownTopicError
        )
    })
})
