import { AdminClient, IAdminClient } from 'node-rdkafka'

import { ensureTopicExists } from './admin'

jest.mock('node-rdkafka', () => ({
    AdminClient: { create: jest.fn() },
    CODES: { ERRORS: { ERR_TOPIC_ALREADY_EXISTS: 36 } },
}))

describe('ensureTopicExists', () => {
    it('uses the consumer authentication and CA when creating a topic', async () => {
        const disconnect = jest.fn()
        jest.mocked(AdminClient.create).mockReturnValue({
            createTopic: (_topic: unknown, _timeout: number, callback: (error?: Error) => void) => callback(),
            disconnect,
        } as unknown as IAdminClient)
        await ensureTopicExists(
            {
                'metadata.broker.list': 'example.com:9092',
                'security.protocol': 'sasl_ssl',
                'sasl.mechanisms': 'SCRAM-SHA-512',
                'sasl.username': 'example-user',
                'sasl.password': 'fake-kafka-credential',
                'ssl.ca.location': '/tmp/example-ca.crt',
                'ssl.endpoint.identification.algorithm': 'https',
            },
            'example-topic'
        )
        expect(AdminClient.create).toHaveBeenCalledWith(
            expect.objectContaining({
                'security.protocol': 'sasl_ssl',
                'sasl.mechanisms': 'SCRAM-SHA-512',
                'sasl.username': 'example-user',
                'sasl.password': 'fake-kafka-credential',
                'ssl.ca.location': '/tmp/example-ca.crt',
                'ssl.endpoint.identification.algorithm': 'https',
            })
        )
        expect(disconnect).toHaveBeenCalled()
    })
})
