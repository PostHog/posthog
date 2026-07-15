import { DateTime } from 'luxon'

import { castTimestampOrNow } from '~/common/utils/utils'
import { ConsoleLogLevel } from '~/ingestion/pipelines/sessionreplay/rrweb-types'
import { TimestampFormat } from '~/types'

import { ExtractedConsoleLog, ExtractedConsoleLogs, SessionConsoleLogRecorder } from './session-console-log-recorder'
import { SessionConsoleLogStore } from './session-console-log-store'

describe('SessionConsoleLogRecorder', () => {
    let recorder: SessionConsoleLogRecorder
    let mockConsoleLogStore: jest.Mocked<SessionConsoleLogStore>

    beforeEach(() => {
        mockConsoleLogStore = {
            storeSessionConsoleLogs: jest.fn().mockResolvedValue(undefined),
            flush: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<SessionConsoleLogStore>

        recorder = new SessionConsoleLogRecorder('test_session_id', 1, 'test_batch_id', mockConsoleLogStore)
    })

    const entry = (level: ConsoleLogLevel, message: string, timestampMs: number = 1000): ExtractedConsoleLog => ({
        level,
        message,
        timestamp: castTimestampOrNow(DateTime.fromMillis(timestampMs), TimestampFormat.ClickHouse),
    })

    // Per-message data as the extract-console-logs step produces it; the recorder only aggregates.
    const createLogs = (overrides: Partial<ExtractedConsoleLogs> = {}): ExtractedConsoleLogs => ({
        consoleLogCount: 0,
        consoleWarnCount: 0,
        consoleErrorCount: 0,
        entries: [],
        ...overrides,
    })

    describe('count aggregation', () => {
        it('folds the level counts across messages into the end result', async () => {
            await recorder.recordSessionLogs(createLogs({ consoleLogCount: 2, consoleWarnCount: 1 }))
            await recorder.recordSessionLogs(createLogs({ consoleLogCount: 1, consoleErrorCount: 3 }))

            const result = recorder.end()

            expect(result).toEqual({ consoleLogCount: 3, consoleWarnCount: 1, consoleErrorCount: 3 })
        })

        it('does not touch the store when a message carries counts but no entries', async () => {
            // The pre-serialized (ml-mirror) path carries counts in metadata only; its console-log
            // store is disabled, so the counts must reach block metadata without a store write.
            await recorder.recordSessionLogs(
                createLogs({ consoleLogCount: 2, consoleWarnCount: 1, consoleErrorCount: 3 })
            )

            expect(mockConsoleLogStore.storeSessionConsoleLogs).not.toHaveBeenCalled()
            expect(recorder.end()).toEqual({ consoleLogCount: 2, consoleWarnCount: 1, consoleErrorCount: 3 })
        })
    })

    describe('entry storage', () => {
        it('stores entries stamped with the session, team, and batch identifiers', async () => {
            await recorder.recordSessionLogs(
                createLogs({
                    consoleLogCount: 1,
                    entries: [entry(ConsoleLogLevel.Info, 'First message', new Date('2024-03-15T10:00:00Z').getTime())],
                })
            )

            expect(mockConsoleLogStore.storeSessionConsoleLogs).toHaveBeenCalledWith([
                {
                    team_id: 1,
                    message: 'First message',
                    level: ConsoleLogLevel.Info,
                    log_source: 'session_replay',
                    log_source_id: 'test_session_id',
                    instance_id: null,
                    timestamp: '2024-03-15 10:00:00.000',
                    batch_id: 'test_batch_id',
                },
            ])
        })

        it('dedupes identical level and message pairs within a message', async () => {
            await recorder.recordSessionLogs(
                createLogs({
                    consoleLogCount: 2,
                    entries: [
                        entry(ConsoleLogLevel.Info, 'Duplicate message', 1000),
                        entry(ConsoleLogLevel.Info, 'Duplicate message', 2000),
                    ],
                })
            )

            expect(mockConsoleLogStore.storeSessionConsoleLogs).toHaveBeenCalledTimes(1)
            expect(mockConsoleLogStore.storeSessionConsoleLogs).toHaveBeenCalledWith([
                expect.objectContaining({ level: ConsoleLogLevel.Info, message: 'Duplicate message' }),
            ])
            // Dedup only affects storage; the counts keep every event.
            expect(recorder.end().consoleLogCount).toBe(2)
        })

        it('keeps same messages with different levels and different messages with the same level', async () => {
            await recorder.recordSessionLogs(
                createLogs({
                    entries: [
                        entry(ConsoleLogLevel.Info, 'Same message'),
                        entry(ConsoleLogLevel.Warn, 'Same message'),
                        entry(ConsoleLogLevel.Info, 'Other message'),
                    ],
                })
            )

            expect(mockConsoleLogStore.storeSessionConsoleLogs).toHaveBeenCalledWith([
                expect.objectContaining({ level: ConsoleLogLevel.Info, message: 'Same message' }),
                expect.objectContaining({ level: ConsoleLogLevel.Warn, message: 'Same message' }),
                expect.objectContaining({ level: ConsoleLogLevel.Info, message: 'Other message' }),
            ])
        })

        it('stores each message batch separately', async () => {
            await recorder.recordSessionLogs(createLogs({ entries: [entry(ConsoleLogLevel.Info, 'First')] }))
            await recorder.recordSessionLogs(createLogs({ entries: [entry(ConsoleLogLevel.Warn, 'Second')] }))

            expect(mockConsoleLogStore.storeSessionConsoleLogs).toHaveBeenCalledTimes(2)
            expect(mockConsoleLogStore.storeSessionConsoleLogs).toHaveBeenNthCalledWith(1, [
                expect.objectContaining({ message: 'First' }),
            ])
            expect(mockConsoleLogStore.storeSessionConsoleLogs).toHaveBeenNthCalledWith(2, [
                expect.objectContaining({ message: 'Second' }),
            ])
        })
    })

    describe('lifecycle', () => {
        it('throws when recording after end', async () => {
            await recorder.recordSessionLogs(createLogs())
            recorder.end()

            await expect(recorder.recordSessionLogs(createLogs())).rejects.toThrow(
                'Cannot record message after end() has been called'
            )
        })

        it('throws when calling end multiple times', async () => {
            await recorder.recordSessionLogs(createLogs())
            recorder.end()

            expect(() => recorder.end()).toThrow('end() has already been called')
        })
    })
})
