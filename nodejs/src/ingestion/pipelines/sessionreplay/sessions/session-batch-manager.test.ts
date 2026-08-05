import { KafkaOffsetManager } from '~/ingestion/pipelines/sessionreplay/kafka/offset-manager'
import { SessionFeatureStore } from '~/ingestion/pipelines/sessionreplay/shared/features/session-feature-store'
import { SessionMetadataStore } from '~/ingestion/pipelines/sessionreplay/shared/metadata/session-metadata-store'
import { createMockEncryptor } from '~/ingestion/pipelines/sessionreplay/shared/test-helpers'
import { RecordingEncryptor } from '~/ingestion/pipelines/sessionreplay/shared/types'

import { SessionBatchFileStorage, SessionBatchFileWriter } from './session-batch-file-storage'
import { SessionBatchManager, SessionBatchManagerConfig } from './session-batch-manager'
import { SessionBatchRecorder } from './session-batch-recorder'
import { SessionConsoleLogStore } from './session-console-log-store'

jest.setTimeout(1000)
jest.mock('./session-batch-recorder')

describe('SessionBatchManager', () => {
    let manager: SessionBatchManager
    let mockOffsetManager: jest.Mocked<KafkaOffsetManager>
    let mockFileStorage: jest.Mocked<SessionBatchFileStorage>
    let mockWriter: jest.Mocked<SessionBatchFileWriter>
    let mockMetadataStore: jest.Mocked<SessionMetadataStore>
    let mockConsoleLogStore: jest.Mocked<SessionConsoleLogStore>
    let mockFeatureStore: jest.Mocked<SessionFeatureStore>
    let mockEncryptor: jest.Mocked<RecordingEncryptor>

    const createMockBatch = (): jest.Mocked<SessionBatchRecorder> =>
        ({
            record: jest.fn(),
            flush: jest.fn().mockResolvedValue(undefined),
            get size() {
                return 0
            },
        }) as unknown as jest.Mocked<SessionBatchRecorder>

    const config = (overrides: Partial<SessionBatchManagerConfig> = {}): SessionBatchManagerConfig => ({
        maxBatchSizeBytes: 100,
        maxBatchAgeMs: 1000,
        maxEventsPerSessionPerBatch: Number.MAX_SAFE_INTEGER,
        offsetManager: mockOffsetManager,
        fileStorage: mockFileStorage,
        metadataStore: mockMetadataStore,
        consoleLogStore: mockConsoleLogStore,
        featureStore: mockFeatureStore,
        encryptor: mockEncryptor,
        ...overrides,
    })

    beforeEach(() => {
        jest.mocked(SessionBatchRecorder).mockImplementation(() => createMockBatch())

        mockOffsetManager = {
            commit: jest.fn().mockResolvedValue(undefined),
            trackOffset: jest.fn(),
        } as unknown as jest.Mocked<KafkaOffsetManager>

        mockWriter = {
            writeSession: jest.fn().mockResolvedValue({ bytesWritten: 0, url: null }),
            finish: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<SessionBatchFileWriter>

        mockFileStorage = {
            newBatch: jest.fn().mockReturnValue(mockWriter),
        } as unknown as jest.Mocked<SessionBatchFileStorage>

        mockMetadataStore = {
            storeSessionBlocks: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<SessionMetadataStore>

        mockConsoleLogStore = {
            storeSessionConsoleLogs: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<SessionConsoleLogStore>

        mockFeatureStore = {
            storeSessionFeatures: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<SessionFeatureStore>

        mockEncryptor = createMockEncryptor()

        manager = new SessionBatchManager(config())
    })

    afterEach(() => {
        jest.clearAllMocks()
    })

    describe('createBatch', () => {
        it('mints a recorder with the configured collaborators', () => {
            manager.createBatch()
            expect(SessionBatchRecorder).toHaveBeenCalledWith(
                mockOffsetManager,
                mockFileStorage,
                mockMetadataStore,
                mockConsoleLogStore,
                mockFeatureStore,
                mockEncryptor,
                Number.MAX_SAFE_INTEGER,
                100
            )
        })

        it('returns a fresh recorder on each call', () => {
            const first = manager.createBatch()
            const second = manager.createBatch()
            expect(second).not.toBe(first)
        })

        // The rate limiter is per-batch, so the configured cap must reach every minted recorder.
        it.each([0, 250, 500, Number.MAX_SAFE_INTEGER])(
            'passes maxEventsPerSessionPerBatch=%p to minted recorders',
            (maxEventsPerSessionPerBatch) => {
                manager = new SessionBatchManager(config({ maxEventsPerSessionPerBatch }))
                manager.createBatch()
                expect(SessionBatchRecorder).toHaveBeenLastCalledWith(
                    mockOffsetManager,
                    mockFileStorage,
                    mockMetadataStore,
                    mockConsoleLogStore,
                    mockFeatureStore,
                    mockEncryptor,
                    maxEventsPerSessionPerBatch,
                    100
                )
            }
        )
    })

    describe('shouldFlush', () => {
        it('flushes when the batch is at or over the size limit', () => {
            const batch = manager.createBatch()
            jest.spyOn(batch, 'size', 'get').mockReturnValue(150)
            expect(manager.shouldFlush(batch, Date.now())).toBe(true)
        })

        it('does not flush when the batch is under the size limit', () => {
            const batch = manager.createBatch()
            jest.spyOn(batch, 'size', 'get').mockReturnValue(50)
            expect(manager.shouldFlush(batch, Date.now())).toBe(false)
        })

        describe('time-based', () => {
            beforeEach(() => {
                jest.useFakeTimers()
            })

            afterEach(() => {
                jest.useRealTimers()
            })

            it('does not flush when under the size limit and the age timeout is not reached', () => {
                const batch = manager.createBatch()
                jest.spyOn(batch, 'size', 'get').mockReturnValue(50)
                const lastFlushTime = Date.now()
                jest.advanceTimersByTime(500)
                expect(manager.shouldFlush(batch, lastFlushTime)).toBe(false)
            })

            it('flushes when the age timeout is reached', () => {
                const batch = manager.createBatch()
                jest.spyOn(batch, 'size', 'get').mockReturnValue(50)
                const lastFlushTime = Date.now()
                jest.advanceTimersByTime(1500)
                expect(manager.shouldFlush(batch, lastFlushTime)).toBe(true)
            })
        })
    })
})
