import { KafkaOffsetManager } from '~/ingestion/pipelines/sessionreplay/kafka/offset-manager'
import { SessionFeatureStore } from '~/ingestion/pipelines/sessionreplay/shared/features/session-feature-store'
import { SessionMetadataStore } from '~/ingestion/pipelines/sessionreplay/shared/metadata/session-metadata-store'
import { createMockEncryptor } from '~/ingestion/pipelines/sessionreplay/shared/test-helpers'
import { RecordingEncryptor } from '~/ingestion/pipelines/sessionreplay/shared/types'

import { SessionBatchFactory, SessionBatchFactoryConfig } from './session-batch-factory'
import { SessionBatchFileStorage } from './session-batch-file-storage'
import { SessionBatchRecorder } from './session-batch-recorder'
import { SessionConsoleLogStore } from './session-console-log-store'

jest.mock('./session-batch-recorder')

describe('SessionBatchFactory', () => {
    let mockOffsetManager: jest.Mocked<KafkaOffsetManager>
    let mockFileStorage: jest.Mocked<SessionBatchFileStorage>
    let mockMetadataStore: jest.Mocked<SessionMetadataStore>
    let mockConsoleLogStore: jest.Mocked<SessionConsoleLogStore>
    let mockFeatureStore: jest.Mocked<SessionFeatureStore>
    let mockEncryptor: jest.Mocked<RecordingEncryptor>

    function makeConfig(overrides: Partial<SessionBatchFactoryConfig> = {}): SessionBatchFactoryConfig {
        return {
            maxEventsPerSessionPerBatch: Number.MAX_SAFE_INTEGER,
            offsetManager: mockOffsetManager,
            fileStorage: mockFileStorage,
            metadataStore: mockMetadataStore,
            consoleLogStore: mockConsoleLogStore,
            featureStore: mockFeatureStore,
            encryptor: mockEncryptor,
            ...overrides,
        }
    }

    beforeEach(() => {
        jest.mocked(SessionBatchRecorder).mockImplementation(() => ({}) as unknown as SessionBatchRecorder)
        mockOffsetManager = {} as unknown as jest.Mocked<KafkaOffsetManager>
        mockFileStorage = {} as unknown as jest.Mocked<SessionBatchFileStorage>
        mockMetadataStore = {} as unknown as jest.Mocked<SessionMetadataStore>
        mockConsoleLogStore = {} as unknown as jest.Mocked<SessionConsoleLogStore>
        mockFeatureStore = {} as unknown as jest.Mocked<SessionFeatureStore>
        mockEncryptor = createMockEncryptor()
    })

    afterEach(() => {
        jest.clearAllMocks()
    })

    it('create returns a fresh, independent recorder each call', () => {
        const factory = new SessionBatchFactory(makeConfig())

        const first = factory.create()
        const second = factory.create()

        expect(first).not.toBe(second)
        expect(SessionBatchRecorder).toHaveBeenCalledTimes(2)
    })

    it.each([0, 250, Number.MAX_SAFE_INTEGER])(
        'create passes maxEventsPerSessionPerBatch=%p and the feature rollout to the recorder',
        (maxEventsPerSessionPerBatch) => {
            const factory = new SessionBatchFactory(
                makeConfig({ maxEventsPerSessionPerBatch, featuresRolloutPercentage: 42 })
            )

            factory.create()

            expect(SessionBatchRecorder).toHaveBeenCalledWith(
                mockOffsetManager,
                mockFileStorage,
                mockMetadataStore,
                mockConsoleLogStore,
                mockFeatureStore,
                mockEncryptor,
                maxEventsPerSessionPerBatch,
                42
            )
        }
    )

    it('defaults the feature rollout to 100 when unset', () => {
        const factory = new SessionBatchFactory(makeConfig())

        factory.create()

        expect(SessionBatchRecorder).toHaveBeenCalledWith(
            expect.anything(),
            expect.anything(),
            expect.anything(),
            expect.anything(),
            expect.anything(),
            expect.anything(),
            Number.MAX_SAFE_INTEGER,
            100
        )
    })
})
