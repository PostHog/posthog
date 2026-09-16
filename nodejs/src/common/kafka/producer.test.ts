import { HighLevelProducer } from 'node-rdkafka'

import { DependencyUnavailableError } from '../utils/db/error'
import { KafkaProducerWrapper } from './producer'

describe('KafkaProducerWrapper.produce', () => {
    let produceMock: jest.Mock
    let connectMock: jest.Mock
    let isConnectedMock: jest.Mock
    let wrapper: KafkaProducerWrapper

    const message = { topic: 't', key: Buffer.from('k'), value: Buffer.from('v') }

    beforeEach(() => {
        // node-rdkafka invokes the trailing (error, offset) callback; call it so produce() resolves.
        produceMock = jest.fn((...args: any[]) => {
            const cb = args[args.length - 1]
            cb(null, 0)
        })
        isConnectedMock = jest.fn().mockReturnValue(true)
        connectMock = jest.fn((_options: any, cb: (error: Error | null) => void) => {
            isConnectedMock.mockReturnValue(true)
            cb(null)
        })
        const mockHighLevelProducer = {
            produce: produceMock,
            connect: connectMock,
            isConnected: isConnectedMock,
            flush: jest.fn((_timeout: number, cb: (error: Error | null) => void) => cb(null)),
            disconnect: jest.fn((cb: (error: Error | null) => void) => cb(null)),
            removeAllListeners: jest.fn(),
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

    it('reconnects and writes the message when the producer is disconnected', async () => {
        isConnectedMock.mockReturnValue(false)

        await wrapper.produce(message)

        expect(connectMock).toHaveBeenCalledTimes(1)
        expect(produceMock).toHaveBeenCalledTimes(1)
    })

    it('reconnects once for the messages that wait on the same reconnect', async () => {
        isConnectedMock.mockReturnValue(false)
        let finishConnect = (): void => {}
        connectMock.mockImplementation((_options: any, cb: (error: Error | null) => void) => {
            finishConnect = () => {
                isConnectedMock.mockReturnValue(true)
                cb(null)
            }
        })

        const produced = Promise.all([wrapper.produce(message), wrapper.produce(message), wrapper.produce(message)])
        finishConnect()
        await produced

        expect(connectMock).toHaveBeenCalledTimes(1)
        expect(produceMock).toHaveBeenCalledTimes(3)
    })

    it('reports a failed reconnect as a retriable dependency error', async () => {
        isConnectedMock.mockReturnValue(false)
        connectMock.mockImplementation((_options: any, cb: (error: Error | null) => void) => cb(new Error('no route')))

        await expect(wrapper.produce(message)).rejects.toBeInstanceOf(DependencyUnavailableError)
        expect(produceMock).not.toHaveBeenCalled()
    })

    it('refuses a write after disconnect instead of reconnecting the producer', async () => {
        await wrapper.disconnect()
        isConnectedMock.mockReturnValue(false)

        await expect(wrapper.produce(message)).rejects.toBeInstanceOf(DependencyUnavailableError)
        expect(connectMock).not.toHaveBeenCalled()
        expect(produceMock).not.toHaveBeenCalled()
    })
})
