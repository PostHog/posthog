import { KafkaProducerWrapper } from '~/common/kafka/producer'

import { buildIngestionProducerRegistry } from './producer-registry'
import { getDefaultKafkaDownstreamProducerEnvConfig, getDefaultKafkaUpstreamProducerEnvConfig } from './producers'

jest.mock('~/common/kafka/producer')

describe('buildIngestionProducerRegistry', () => {
    const config = { ...getDefaultKafkaUpstreamProducerEnvConfig(), ...getDefaultKafkaDownstreamProducerEnvConfig() }

    beforeEach(() => {
        jest.mocked(KafkaProducerWrapper.createWithConfig).mockReset()
        jest.mocked(KafkaProducerWrapper.createWithConfig).mockResolvedValue({} as KafkaProducerWrapper)
    })

    it.each([
        [true, 0],
        [false, 2],
    ])('with INGESTION_OUTPUTS_DISABLED=%s connects %i Kafka producers', async (disabled, connected) => {
        await buildIngestionProducerRegistry(undefined, { ...config, INGESTION_OUTPUTS_DISABLED: disabled })

        expect(KafkaProducerWrapper.createWithConfig).toHaveBeenCalledTimes(connected)
    })
})
