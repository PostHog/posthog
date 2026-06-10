import { dayjs } from 'lib/dayjs'

import { sessionIdTimestampBounds } from './replayCaptureDiagnosticsPanelLogic'

describe('sessionIdTimestampBounds', () => {
    const now = dayjs('2026-06-10T12:00:00Z')
    // UUIDv7 whose first 48 bits encode 2025-06-13T02:53:58.656Z
    const sessionStart = dayjs(parseInt('019767355800', 16))
    const uuidv7SessionId = '01976735-5800-7abc-8def-0123456789ab'

    it.each([
        [
            'uuidv7 id derives a window around the embedded timestamp',
            uuidv7SessionId,
            { from: sessionStart.subtract(3, 'day'), to: sessionStart.add(4, 'day') },
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
