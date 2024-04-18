import { HighLevelProducer } from 'node-rdkafka'

import { produce } from '../../../../../src/kafka/producer'
import { NetworkPayloadsIngester } from '../../../../../src/main/ingestion-queues/session-recording/services/network-payloads-ingester'
import { OffsetHighWaterMarker } from '../../../../../src/main/ingestion-queues/session-recording/services/offset-high-water-marker'
import { IncomingRecordingMessage } from '../../../../../src/main/ingestion-queues/session-recording/types'
import { PluginsServerConfig } from '../../../../../src/types'
import { status } from '../../../../../src/utils/status'

jest.mock('../../../../../src/utils/status')
jest.mock('../../../../../src/kafka/producer')

const makeIncomingMessage = (
    data: Record<string, unknown>[],
    networkPayloadIngestionEnabled: boolean
): IncomingRecordingMessage => {
    return {
        distinct_id: '',
        eventsRange: { start: 0, end: 0 },
        eventsByWindowId: { window_id: data.map((d) => ({ type: 6, timestamp: 0, data: { ...d } })) },
        metadata: {
            lowOffset: 0,
            highOffset: 0,
            partition: 0,
            topic: 'topic',
            timestamp: 0,
            networkPayloadIngestionEnabled,
            rawSize: 0,
        },
        session_id: '',
        team_id: 0,
        snapshot_source: 'should not effect this ingestion route',
    }
}

describe('network payloads ingester', () => {
    let networkPayloadsIngester: NetworkPayloadsIngester
    const mockProducer: jest.Mock = jest.fn()

    beforeEach(() => {
        mockProducer.mockClear()
        mockProducer['connect'] = jest.fn()
        mockProducer['isConnected'] = () => true

        const mockedHighWaterMarker = { isBelowHighWaterMark: jest.fn() } as unknown as OffsetHighWaterMarker
        networkPayloadsIngester = new NetworkPayloadsIngester(
            {} as PluginsServerConfig,
            mockProducer as unknown as HighLevelProducer,
            mockedHighWaterMarker
        )
    })
    describe('when enabled on team', () => {
        test.todo('wat')
    })

    describe('when disabled on team', () => {
        test('it drops payloads', async () => {
            await networkPayloadsIngester.consume(makeIncomingMessage([{ plugin: 'rrweb/network@1' }], false))
            expect(jest.mocked(produce)).not.toHaveBeenCalled()
        })
        test('it does not drop events with no payloads', async () => {
            await networkPayloadsIngester.consume(makeIncomingMessage([{ plugin: 'some-other-plugin' }], false))
            expect(jest.mocked(status.debug).mock.calls).toEqual([])
            expect(jest.mocked(produce)).not.toHaveBeenCalled()
        })
    })
})
