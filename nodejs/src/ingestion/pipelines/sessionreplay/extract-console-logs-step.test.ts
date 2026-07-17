import { DateTime } from 'luxon'

import { PipelineResultType } from '~/ingestion/framework/results'
import { ParsedMessageData } from '~/ingestion/pipelines/sessionreplay/kafka/types'
import { ConsoleLogLevel, RRWebEventType } from '~/ingestion/pipelines/sessionreplay/rrweb-types'
import { ExtractedConsoleLogs } from '~/ingestion/pipelines/sessionreplay/sessions/session-console-log-recorder'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'

import { ExtractConsoleLogsStepInput, createExtractConsoleLogsStep } from './extract-console-logs-step'

describe('extract-console-logs-step', () => {
    const team = (consoleLogIngestionEnabled: boolean = true): TeamForReplay => ({
        teamId: 1,
        consoleLogIngestionEnabled,
        aiTrainingOptedIn: true,
        firstPartyHosts: [],
    })

    const createConsoleLogEvent = ({
        level,
        payload,
        timestamp,
    }: {
        level: unknown
        payload: unknown[]
        timestamp: number
    }) => ({
        type: RRWebEventType.Plugin,
        timestamp,
        data: {
            plugin: 'rrweb/console@1',
            payload: {
                level,
                payload,
            },
        },
    })

    const createMessage = (events: any[]): ParsedMessageData => ({
        distinct_id: 'distinct_id',
        session_id: 'session_id',
        token: null,
        eventsByWindowId: {
            window1: events,
        },
        eventsRange: {
            start: DateTime.fromMillis(events[0]?.timestamp || 0),
            end: DateTime.fromMillis(events[events.length - 1]?.timestamp || 0),
        },
        snapshot_source: null,
        snapshot_library: null,
        metadata: {
            partition: 1,
            topic: 'test',
            offset: 0,
            timestamp: 0,
            rawSize: 0,
        },
    })

    const step = createExtractConsoleLogsStep()

    const extract = async (
        extractingTeam: TeamForReplay,
        message: ParsedMessageData
    ): Promise<ExtractedConsoleLogs> => {
        const result = await step({ team: extractingTeam, parsedMessage: message })
        if (result.type !== PipelineResultType.OK) {
            throw new Error('expected ok result')
        }
        return result.value.logs
    }

    it('counts events by level and collects their entries', async () => {
        const logs = await extract(
            team(),
            createMessage([
                createConsoleLogEvent({ level: 'info', payload: ['Log 1'], timestamp: 1000 }),
                createConsoleLogEvent({ level: 'warn', payload: ['Warning'], timestamp: 2000 }),
                createConsoleLogEvent({ level: 'error', payload: ['Error'], timestamp: 3000 }),
                createConsoleLogEvent({ level: 'info', payload: ['Log 2'], timestamp: 4000 }),
            ])
        )

        expect(logs.consoleLogCount).toBe(2)
        expect(logs.consoleWarnCount).toBe(1)
        expect(logs.consoleErrorCount).toBe(1)
        expect(logs.entries).toHaveLength(4)
    })

    it('counts duplicate messages without deduplicating entries', async () => {
        // Dedup for storage is the recorder's job; the counts must include every event.
        const logs = await extract(
            team(),
            createMessage([
                createConsoleLogEvent({ level: 'info', payload: ['Duplicate'], timestamp: 1000 }),
                createConsoleLogEvent({ level: 'info', payload: ['Duplicate'], timestamp: 2000 }),
            ])
        )

        expect(logs.consoleLogCount).toBe(2)
        expect(logs.entries).toHaveLength(2)
    })

    it('stamps entries with the level, joined message, and ClickHouse timestamp', async () => {
        const logs = await extract(
            team(),
            createMessage([
                createConsoleLogEvent({
                    level: 'warn',
                    payload: ['First part', 'second part'],
                    timestamp: new Date('2024-03-15T10:00:00Z').getTime(),
                }),
            ])
        )

        expect(logs.entries).toEqual([
            {
                level: ConsoleLogLevel.Warn,
                message: 'First part second part',
                timestamp: '2024-03-15 10:00:00.000',
            },
        ])
    })

    it('keeps only string payload elements in the message', async () => {
        const logs = await extract(
            team(),
            createMessage([
                createConsoleLogEvent({
                    level: 'info',
                    payload: [
                        'Message with',
                        { complex: 'object' },
                        123,
                        ['nested', 'array'],
                        'multiple strings',
                        null,
                        undefined,
                        true,
                    ],
                    timestamp: 1000,
                }),
            ])
        )

        expect(logs.entries[0].message).toBe('Message with multiple strings')
    })

    it('ignores non-console events', async () => {
        const logs = await extract(
            team(),
            createMessage([
                { type: RRWebEventType.Meta, timestamp: 1000, data: {} },
                {
                    type: RRWebEventType.Plugin,
                    timestamp: 2000,
                    data: {
                        plugin: 'some-other-plugin',
                        payload: { level: 'log', content: ['Not a console event'] },
                    },
                },
            ])
        )

        expect(logs).toEqual({ consoleLogCount: 0, consoleWarnCount: 0, consoleErrorCount: 0, entries: [] })
    })

    describe('level mapping', () => {
        const testCases = [
            // Info level mappings
            { input: 'info', expected: ConsoleLogLevel.Info },
            { input: 'log', expected: ConsoleLogLevel.Info },
            { input: 'debug', expected: ConsoleLogLevel.Info },
            { input: 'trace', expected: ConsoleLogLevel.Info },
            { input: 'dir', expected: ConsoleLogLevel.Info },
            { input: 'dirxml', expected: ConsoleLogLevel.Info },
            { input: 'group', expected: ConsoleLogLevel.Info },
            { input: 'groupCollapsed', expected: ConsoleLogLevel.Info },
            { input: 'count', expected: ConsoleLogLevel.Info },
            { input: 'timeEnd', expected: ConsoleLogLevel.Info },
            { input: 'timeLog', expected: ConsoleLogLevel.Info },
            // Warn level mappings
            { input: 'warn', expected: ConsoleLogLevel.Warn },
            { input: 'countReset', expected: ConsoleLogLevel.Warn },
            // Error level mappings
            { input: 'error', expected: ConsoleLogLevel.Error },
            { input: 'assert', expected: ConsoleLogLevel.Error },
            // Edge cases fall back to Info
            { input: 'unknown', expected: ConsoleLogLevel.Info },
            { input: '', expected: ConsoleLogLevel.Info },
            { input: undefined, expected: ConsoleLogLevel.Info },
            { input: null, expected: ConsoleLogLevel.Info },
            { input: 123, expected: ConsoleLogLevel.Info },
        ]

        test.each(testCases)('maps browser level $input to $expected', async ({ input, expected }) => {
            const logs = await extract(
                team(),
                createMessage([createConsoleLogEvent({ level: input, payload: ['test message'], timestamp: 1000 })])
            )

            expect(logs.entries).toEqual([expect.objectContaining({ level: expected, message: 'test message' })])
        })
    })

    it('extracts nothing when console log ingestion is disabled for the team', async () => {
        const logs = await extract(
            team(false),
            createMessage([createConsoleLogEvent({ level: 'log', payload: ['test message'], timestamp: 1000 })])
        )

        expect(logs).toEqual({ consoleLogCount: 0, consoleWarnCount: 0, consoleErrorCount: 0, entries: [] })
    })

    it('uses the metadata counts for pre-serialized messages without collecting entries', async () => {
        const message = createMessage([])
        message.eventsByWindowId = {}
        message.preSerialized = {
            lines: Buffer.from(''),
            events: [],
            consoleLogCount: 2,
            consoleWarnCount: 1,
            consoleErrorCount: 3,
        }

        const logs = await extract(team(), message)

        expect(logs).toEqual({ consoleLogCount: 2, consoleWarnCount: 1, consoleErrorCount: 3, entries: [] })
    })

    it('preserves the step input alongside the extracted logs', async () => {
        const parsedMessage = createMessage([
            createConsoleLogEvent({ level: 'error', payload: ['Boom'], timestamp: 1000 }),
        ])
        const stepWithExtras = createExtractConsoleLogsStep<ExtractConsoleLogsStepInput & { extra: string }>()

        const result = await stepWithExtras({ team: team(), parsedMessage, extra: 'kept' })

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.logs.consoleErrorCount).toBe(1)
            expect(result.value.extra).toBe('kept')
        }
    })
})
