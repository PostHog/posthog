import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'

import { initKeaTests } from '~/test/init'

import { replayCaptureDiagnosticsPanelLogic, sessionIdTimestampBounds } from './replayCaptureDiagnosticsPanelLogic'

function uuidv7WithEmbeddedStart(startMs: number): string {
    const hex = startMs.toString(16).padStart(12, '0')
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-7abc-8def-0123456789ab`
}

describe('replayCaptureDiagnosticsPanelLogic', () => {
    describe('sessionIdTimestampBounds', () => {
        const now = dayjs('2026-06-10T12:00:00Z')
        // UUIDv7 whose first 48 bits encode 2025-06-13T02:53:58.656Z
        const sessionStart = dayjs(parseInt('019767355800', 16))
        const uuidv7SessionId = '01976735-5800-7abc-8def-0123456789ab'
        // UUIDv7 whose embedded timestamp is six hours after `now` — a mildly
        // fast client clock, still inside the now + 1 day grace.
        const futureStart = now.add(6, 'hour')
        const futureUuidv7SessionId = uuidv7WithEmbeddedStart(futureStart.valueOf())

        it.each([
            [
                'uuidv7 id derives a window around the embedded timestamp',
                uuidv7SessionId,
                { from: sessionStart.subtract(3, 'day'), to: sessionStart.add(4, 'day') },
            ],
            [
                'uuidv7 id a few hours in the future stays inside the grace and derives a window',
                futureUuidv7SessionId,
                { from: futureStart.subtract(3, 'day'), to: futureStart.add(4, 'day') },
            ],
            [
                'non-uuid id falls back to the retention window',
                'custom-session-id',
                { from: now.subtract(90, 'day'), to: now.add(1, 'day') },
            ],
            [
                'uuidv4 id falls back to the retention window',
                '7c10ab30-3a9c-4b75-89ce-09e51c826989',
                { from: now.subtract(90, 'day'), to: now.add(1, 'day') },
            ],
            [
                'uuidv7 with an implausibly old embedded timestamp falls back',
                // first 48 bits encode 1970-02-19, long before uuidv7 session ids existed
                '0000ffff-ffff-7abc-8def-0123456789ab',
                { from: now.subtract(90, 'day'), to: now.add(1, 'day') },
            ],
            [
                'uuidv7 with a far-future embedded timestamp falls back',
                'ffffffff-ffff-7abc-8def-0123456789ab',
                { from: now.subtract(90, 'day'), to: now.add(1, 'day') },
            ],
        ])('%s', (_name, sessionId, expected) => {
            const bounds = sessionIdTimestampBounds(sessionId, now)
            expect(bounds.from.toISOString()).toEqual(expected.from.toISOString())
            expect(bounds.to.toISOString()).toEqual(expected.to.toISOString())
        })
    })

    describe('loadSessionEventProperties', () => {
        let queryHogQL: jest.SpyInstance

        // A UUIDv7 whose embedded timestamp is one hour ago, so the derived
        // window is narrower than the 90-day fallback and a retry is possible.
        const recentUuidv7SessionId = uuidv7WithEmbeddedStart(dayjs().subtract(1, 'hour').valueOf())

        beforeEach(() => {
            initKeaTests()
            queryHogQL = jest.spyOn(api, 'queryHogQL')
        })

        afterEach(() => {
            queryHogQL.mockRestore()
        })

        async function loadFor(sessionId: string): Promise<Record<string, any> | null> {
            const logic = replayCaptureDiagnosticsPanelLogic({ sessionId })
            logic.mount()
            await expectLogic(logic, () => {
                logic.actions.loadSessionEventProperties()
            }).toDispatchActions(['loadSessionEventPropertiesSuccess'])
            return logic.values.sessionEventProperties
        }

        it('parses the row from the tight window without a retry', async () => {
            queryHogQL.mockResolvedValue({ results: [['{"$has_recording":true}']] } as any)

            const properties = await loadFor(recentUuidv7SessionId)

            expect(properties).toEqual({ $has_recording: true })
            expect(queryHogQL).toHaveBeenCalledTimes(1)
        })

        it('retries with the fallback window when the tight uuidv7 window is empty', async () => {
            queryHogQL
                .mockResolvedValueOnce({ results: [] } as any)
                .mockResolvedValueOnce({ results: [['{"$has_recording":true}']] } as any)

            const properties = await loadFor(recentUuidv7SessionId)

            expect(properties).toEqual({ $has_recording: true })
            expect(queryHogQL).toHaveBeenCalledTimes(2)
        })

        it('does not retry for a non-uuidv7 id that already used the fallback window', async () => {
            queryHogQL.mockResolvedValue({ results: [] } as any)

            const properties = await loadFor('custom-session-id')

            expect(properties).toBeNull()
            expect(queryHogQL).toHaveBeenCalledTimes(1)
        })
    })
})
