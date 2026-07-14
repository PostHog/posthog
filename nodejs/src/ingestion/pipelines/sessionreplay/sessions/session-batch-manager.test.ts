import { SessionFeatureStore } from '~/ingestion/pipelines/sessionreplay/shared/features/session-feature-store'
import { SessionMetadataStore } from '~/ingestion/pipelines/sessionreplay/shared/metadata/session-metadata-store'
import { createMockEncryptor } from '~/ingestion/pipelines/sessionreplay/shared/test-helpers'
import { RecordingEncryptor } from '~/ingestion/pipelines/sessionreplay/shared/types'

import { SessionBatchFileStorage } from './session-batch-file-storage'
import { SessionBatchManager, SessionBatchManagerConfig } from './session-batch-manager'
import { SessionBatchRecorder } from './session-batch-recorder'
import { SessionConsoleLogStore } from './session-console-log-store'

jest.mock('./session-batch-recorder')

describe('SessionBatchManager', () => {
    let mockFileStorage: jest.Mocked<SessionBatchFileStorage>
    let mockMetadataStore: jest.Mocked<SessionMetadataStore>
    let mockConsoleLogStore: jest.Mocked<SessionConsoleLogStore>
    let mockFeatureStore: jest.Mocked<SessionFeatureStore>
    let mockEncryptor: jest.Mocked<RecordingEncryptor>

    function makeConfig(overrides: Partial<SessionBatchManagerConfig> = {}): SessionBatchManagerConfig {
        return {
            maxEventsPerSessionPerBatch: Number.MAX_SAFE_INTEGER,
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
        const manager = new SessionBatchManager(makeConfig())

        const first = manager.createBatch()
        const second = manager.createBatch()

        expect(first).not.toBe(second)
        expect(SessionBatchRecorder).toHaveBeenCalledTimes(2)
    })

    it.each([0, 250, Number.MAX_SAFE_INTEGER])(
        'create passes maxEventsPerSessionPerBatch=%p and the feature rollout to the recorder',
        (maxEventsPerSessionPerBatch) => {
            const manager = new SessionBatchManager(
                makeConfig({ maxEventsPerSessionPerBatch, featuresRolloutPercentage: 42 })
            )

            manager.createBatch()

            expect(SessionBatchRecorder).toHaveBeenCalledWith(
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
        const manager = new SessionBatchManager(makeConfig())

        manager.createBatch()

        expect(SessionBatchRecorder).toHaveBeenCalledWith(
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
