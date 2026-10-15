import { EventType } from 'posthog-js/rrweb-types'

import { RecordingSnapshot } from '~/types'

import { ExportedSessionRecordingFileV2 } from '../../file-playback/types'
import { buildDebugReplayData } from './debugReplayData'

const START = 1_700_000_000_000

function consoleSnapshot(offsetMs: number, level: string, message: string): RecordingSnapshot {
    return {
        type: EventType.Plugin,
        timestamp: START + offsetMs,
        windowId: 1,
        data: { plugin: 'rrweb/console@1', payload: { level, payload: [message], trace: ['at app.js:1'] } },
    } as unknown as RecordingSnapshot
}

function exportOf(snapshots: RecordingSnapshot[]): ExportedSessionRecordingFileV2 {
    return { version: '2023-04-28', data: { id: 'session-1', person: undefined, snapshots } }
}

describe('buildDebugReplayData', () => {
    it('keeps page, console and network entries and drops DOM snapshot content', () => {
        const result = JSON.parse(
            buildDebugReplayData(
                exportOf([
                    {
                        type: EventType.Meta,
                        timestamp: START,
                        windowId: 1,
                        data: { href: 'https://example.com/checkout', width: 1200, height: 800 },
                    } as unknown as RecordingSnapshot,
                    {
                        type: EventType.FullSnapshot,
                        timestamp: START + 10,
                        windowId: 1,
                        data: { node: { secretMarkup: 'dom-content-that-must-not-be-sent' } },
                    } as unknown as RecordingSnapshot,
                    consoleSnapshot(2500, 'error', 'Payment failed'),
                    {
                        type: EventType.Plugin,
                        timestamp: START + 4000,
                        windowId: 1,
                        data: {
                            plugin: 'rrweb/network@1',
                            payload: {
                                requests: [
                                    {
                                        name: 'https://example.com/api/pay',
                                        method: 'POST',
                                        responseStatus: 500,
                                        duration: 120.4,
                                        initiatorType: 'fetch',
                                    },
                                ],
                            },
                        },
                    } as unknown as RecordingSnapshot,
                ])
            )
        )

        expect(result).toMatchObject({
            session_id: 'session-1',
            duration_seconds: 4,
            snapshot_counts: { Meta: 1, FullSnapshot: 1, Plugin: 2 },
            timeline: [
                { t: 0, kind: 'page', url: 'https://example.com/checkout', viewport: '1200x800' },
                { t: 2.5, kind: 'console', level: 'error', message: 'Payment failed', trace: ['at app.js:1'] },
                { t: 4, kind: 'network', method: 'POST', url: 'https://example.com/api/pay', status: 500 },
            ],
        })
        expect(result.omitted).toBeUndefined()
        expect(JSON.stringify(result)).not.toContain('dom-content-that-must-not-be-sent')
    })

    it('stays within budget and parseable, dropping plain logs before errors', () => {
        const snapshots = [
            ...Array.from({ length: 200 }, (_, i) => consoleSnapshot(i, 'info', `noise ${i} ${'x'.repeat(100)}`)),
            consoleSnapshot(900, 'error', 'the one error'),
        ]

        const serialized = buildDebugReplayData(exportOf(snapshots), 4000)
        const result = JSON.parse(serialized)

        expect(serialized.length).toBeLessThanOrEqual(4000)
        expect(result.timeline).toContainEqual(expect.objectContaining({ level: 'error', message: 'the one error' }))
        expect(result.omitted).toMatchObject({ problems: 0 })
        expect(result.omitted.other).toBeGreaterThan(0)
        expect(result.timeline.length + result.omitted.other).toBe(201)
    })
})
