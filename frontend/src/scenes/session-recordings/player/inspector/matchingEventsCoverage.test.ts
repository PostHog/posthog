import { dayjs } from 'lib/dayjs'
import { allMatchingEventsOutsideWindow } from 'scenes/session-recordings/player/inspector/playerInspectorLogic'

import { MatchedRecordingEvent } from '~/types'

describe('allMatchingEventsOutsideWindow', () => {
    const start = dayjs('2024-01-01T10:00:00.000Z')
    const end = dayjs('2024-01-01T10:30:00.000Z')

    const at = (iso: string): MatchedRecordingEvent => ({ uuid: iso, timestamp: iso })

    test.each<[string, MatchedRecordingEvent[] | null, ReturnType<typeof dayjs> | null, boolean]>([
        ['no matching events', [], start, false],
        ['null matching events', null, start, false],
        ['no recording bounds yet', [at('2024-01-01T10:15:00.000Z')], null, false],
        ['match inside the window is covered', [at('2024-01-01T10:15:00.000Z')], start, false],
        ['match on the start boundary is covered', [at('2024-01-01T10:00:00.000Z')], start, false],
        ['match on the end boundary is covered', [at('2024-01-01T10:30:00.000Z')], start, false],
        ['all matches after the window are uncovered', [at('2024-01-01T11:00:00.000Z')], start, true],
        ['all matches before the window are uncovered', [at('2024-01-01T09:00:00.000Z')], start, true],
        [
            'one match inside keeps the recording covered',
            [at('2024-01-01T09:00:00.000Z'), at('2024-01-01T10:15:00.000Z')],
            start,
            false,
        ],
    ])('%s', (_name, matchingEvents, startBound, expected) => {
        expect(allMatchingEventsOutsideWindow(matchingEvents, startBound, startBound ? end : null)).toBe(expected)
    })
})
