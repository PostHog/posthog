import { DateTime } from 'luxon'

import { parseJSON } from '~/common/utils/json-parse'
import { PipelineResultType } from '~/ingestion/framework/results'
import { ParsedMessageData } from '~/ingestion/pipelines/sessionreplay/kafka/types'
import { RRWebEventType } from '~/ingestion/pipelines/sessionreplay/rrweb-types'
import { SerializedSessionData } from '~/ingestion/pipelines/sessionreplay/sessions/snappy-session-recorder'
import { createMockSessionKey } from '~/ingestion/pipelines/sessionreplay/shared/test-helpers'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'

import { createExtractSessionDataStep } from './extract-session-data-step'

describe('extract-session-data-step', () => {
    const team: TeamForReplay = {
        teamId: 7,
        consoleLogIngestionEnabled: false,
        aiTrainingOptedIn: true,
        firstPartyHosts: [],
    }

    const createMessage = (
        windowId: string,
        events: any[],
        overrides: Partial<ParsedMessageData> = {}
    ): ParsedMessageData => ({
        distinct_id: 'distinct_id',
        session_id: 'session_id',
        token: null,
        eventsByWindowId: {
            [windowId]: events,
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
        ...overrides,
    })

    const step = createExtractSessionDataStep()

    const extract = async (message: ParsedMessageData): Promise<SerializedSessionData> => {
        const result = await step({
            team,
            parsedMessage: message,
            retentionPeriod: '30d',
            sessionKey: createMockSessionKey(),
        })
        if (result.type !== PipelineResultType.OK) {
            throw new Error('expected ok result')
        }
        return result.value.data
    }

    const parseChunks = (chunks: Buffer[]): [string, any][] =>
        Buffer.concat(chunks)
            .toString()
            .trim()
            .split('\n')
            .filter(Boolean)
            .map((line) => parseJSON(line))

    describe('serialization', () => {
        it('serializes events as JSONL chunks of [windowId, event]', async () => {
            const events = [
                {
                    type: RRWebEventType.FullSnapshot,
                    timestamp: new Date('2025-01-01T01:00:00Z').getTime(),
                    data: { source: 1, adds: [{ parentId: 1, nextId: 2, node: { tag: 'div' } }] },
                },
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: new Date('2025-01-01T01:00:01Z').getTime(),
                    data: { source: 2, texts: [{ id: 1, value: 'Updated text' }] },
                },
            ]

            const data = await extract(createMessage('window1', events))

            expect(parseChunks(data.chunks)).toEqual([
                ['window1', events[0]],
                ['window1', events[1]],
            ])
            expect(data.eventCount).toBe(2)
            expect(data.rawBytes).toBe(Buffer.concat(data.chunks).length)
        })

        it('serializes events from multiple windows in window order', async () => {
            const events = {
                window1: [{ type: RRWebEventType.Meta, timestamp: 1000, data: { href: 'https://example.com' } }],
                window2: [{ type: RRWebEventType.Custom, timestamp: 2000, data: { tag: 'user-interaction' } }],
            }
            const message = createMessage('', [])
            message.eventsByWindowId = events

            const data = await extract(message)

            expect(parseChunks(data.chunks)).toEqual([
                ['window1', events.window1[0]],
                ['window2', events.window2[0]],
            ])
            expect(data.eventCount).toBe(2)
        })

        it('produces no chunks for an empty events array', async () => {
            const data = await extract(createMessage('window1', []))

            expect(data.chunks).toEqual([])
            expect(data.rawBytes).toBe(0)
            expect(data.eventCount).toBe(0)
        })
    })

    describe('event counting', () => {
        // MouseInteraction (source 2) types: 2=Click, 3=ContextMenu, 4=DblClick count as clicks;
        // 0=MouseUp and 1=MouseDown do not. Input (source 5) counts as keypress. MouseMove (1)
        // and TouchMove (6) count as mouse activity; Scroll (3) and ViewportResize (4) do not.
        it.each([
            [
                'clicks',
                [
                    { source: 2, type: 2 },
                    { source: 2, type: 3 },
                    { source: 2, type: 4 },
                    { source: 2, type: 0 },
                    { source: 2, type: 1 },
                ],
                { clickCount: 3, keypressCount: 0 },
            ],
            [
                'keypresses',
                [{ source: 5 }, { source: 5 }, { source: 2 }, { source: 3 }],
                { clickCount: 0, keypressCount: 2 },
            ],
            [
                'mouse activity',
                [{ source: 1 }, { source: 6 }, { source: 3 }, { source: 4 }, { source: 5 }],
                { mouseActivityCount: 2 },
            ],
        ])('counts %s', async (_name, eventData, expected) => {
            const events = eventData.map((data, i) => ({
                type: RRWebEventType.IncrementalSnapshot,
                timestamp: 1000 + i,
                data,
            }))

            const data = await extract(createMessage('window1', events))

            expect(data).toMatchObject(expected)
        })
    })

    describe('urls', () => {
        it('collects hrefs in event order, repeats included', async () => {
            const events = [
                { type: RRWebEventType.Meta, timestamp: 1000, data: { href: 'https://example1.com' } },
                { type: RRWebEventType.Meta, timestamp: 2000, data: { href: 'https://example2.com' } },
                { type: RRWebEventType.Meta, timestamp: 3000, data: { href: 'https://example1.com' } },
            ]

            const data = await extract(createMessage('window1', events))

            // Dedup, truncation, and capping are the recorder's job.
            expect(data.urls).toEqual(['https://example1.com', 'https://example2.com', 'https://example1.com'])
        })

        it('collects no urls from events without hrefs', async () => {
            const events = [{ type: RRWebEventType.Meta, timestamp: 1000, data: {} }]

            const data = await extract(createMessage('window1', events))

            expect(data.urls).toEqual([])
        })
    })

    describe('message fields', () => {
        it('passes through distinct id and events range', async () => {
            const message = createMessage('window1', [{ type: RRWebEventType.Meta, timestamp: 1000, data: {} }])

            const data = await extract(message)

            expect(data.distinctId).toBe('distinct_id')
            expect(data.eventsRange).toEqual(message.eventsRange)
        })

        it('defaults the snapshot source to web and keeps the library null', async () => {
            const data = await extract(createMessage('window1', []))

            expect(data.snapshotSource).toBe('web')
            expect(data.snapshotLibrary).toBeNull()
        })

        it('truncates snapshot source and library to 1000 characters', async () => {
            const longString = 'a'.repeat(2000)
            const message = createMessage('window1', [], {
                snapshot_source: longString,
                snapshot_library: longString,
            })

            const data = await extract(message)

            expect(data.snapshotSource).toBe('a'.repeat(1000))
            expect(data.snapshotLibrary).toBe('a'.repeat(1000))
        })
    })

    describe('pre-serialized fast path (native anonymizer)', () => {
        it('passes the block lines through as one chunk and derives counts from the per-event metadata', async () => {
            // Flag bits mirror rust/replay-anonymizer-node `snapshot.rs`: 1=active 2=click 4=keypress 8=mouse.
            const t0 = DateTime.fromISO('2025-01-01T01:00:00Z').toMillis()
            const lines = Buffer.from(
                `["w1",{"type":4,"timestamp":${t0},"data":{"href":"https://example.com/[redacted]"}}]\n` +
                    `["w1",{"type":3,"timestamp":${t0 + 1000},"data":{"source":2,"type":2}}]\n` +
                    `["w1",{"type":3,"timestamp":${t0 + 2000},"data":{"source":5,"text":"****"}}]\n`
            )
            const message = createMessage('w1', [])
            message.eventsByWindowId = {}
            message.eventsRange = { start: DateTime.fromMillis(t0), end: DateTime.fromMillis(t0 + 2000) }
            message.preSerialized = {
                lines,
                events: [
                    { ts: t0, flags: 0, href: 'https://example.com/[redacted]' },
                    { ts: t0 + 1000, flags: 1 | 2 | 8 }, // click: active + click + mouse
                    { ts: t0 + 2000, flags: 1 | 4 }, // input: active + keypress
                ],
                consoleLogCount: 0,
                consoleWarnCount: 0,
                consoleErrorCount: 0,
            }

            const data = await extract(message)

            expect(data.chunks).toEqual([lines])
            expect(data.rawBytes).toBe(lines.length)
            expect(data.eventCount).toBe(3)
            expect(data.clickCount).toBe(1)
            expect(data.keypressCount).toBe(1)
            expect(data.mouseActivityCount).toBe(1)
            expect(data.urls).toEqual(['https://example.com/[redacted]'])
            expect(data.segmentationEvents).toEqual([
                { timestamp: t0, isActive: false },
                { timestamp: t0 + 1000, isActive: true },
                { timestamp: t0 + 2000, isActive: true },
            ])
        })
    })

    describe('session ref', () => {
        it('attaches the session ref built from the team, message, and resolved attributes, preserving the input', async () => {
            const parsedMessage = createMessage('window1', [
                { type: RRWebEventType.Meta, timestamp: 1000, data: { href: 'https://example.com' } },
            ])
            const sessionKey = createMockSessionKey()
            const stepWithExtras = createExtractSessionDataStep<Parameters<typeof step>[0] & { extra: string }>()

            const result = await stepWithExtras({
                team,
                parsedMessage,
                retentionPeriod: '1y',
                sessionKey,
                extra: 'kept',
            })

            expect(result.type).toBe(PipelineResultType.OK)
            if (result.type === PipelineResultType.OK) {
                expect(result.value.session).toEqual({
                    teamId: 7,
                    sessionId: 'session_id',
                    partition: 1,
                    retentionPeriod: '1y',
                    sessionKey,
                })
                expect(result.value.data.urls).toEqual(['https://example.com'])
                expect(result.value.extra).toBe('kept')
            }
        })
    })
})
