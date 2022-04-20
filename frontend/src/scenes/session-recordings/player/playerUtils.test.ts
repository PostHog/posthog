import { RecordingSegment } from '~/types'
import { parseMetadataResponse } from '../sessionRecordingLogic'
import recordingMetaJson from '../__mocks__/recording_meta.json'
import {
    comparePlayerPositions,
    convertPlayerPositionToX,
    convertXToPlayerPosition,
    getEpochTimeFromPlayerPosition,
    getPlayerPositionFromEpochTime,
    getPlayerPositionFromPlayerTime,
    getPlayerTimeFromPlayerPosition,
    getSegmentFromPlayerPosition,
    guessPlayerPositionFromEpochTimeWithoutWindowId,
} from './playerUtils'

const metadata = parseMetadataResponse(recordingMetaJson['session_recording'])
const segments: RecordingSegment[] = metadata.segments ?? []

describe('comparePlayerPositions', () => {
    it('works when the window_ids are the same', () => {
        expect(comparePlayerPositions({ windowId: '1', time: 0 }, { windowId: '1', time: 0 }, segments)).toEqual(0)
        expect(comparePlayerPositions({ windowId: '1', time: 1 }, { windowId: '1', time: 100 }, segments)).toEqual(-99)
        expect(comparePlayerPositions({ windowId: '1', time: 100 }, { windowId: '1', time: 1 }, segments)).toEqual(99)
    })

    it('works when the window_ids are different', () => {
        expect(
            comparePlayerPositions(
                { windowId: '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f', time: 0 },
                { windowId: '17da0b382b1165-00c767cd61e6e3-1c306851-13c680-17da0b382b210b', time: 0 },
                segments
            )
        ).toEqual(-1)
        expect(
            comparePlayerPositions(
                { windowId: '17da0b382b1165-00c767cd61e6e3-1c306851-13c680-17da0b382b210b', time: 0 },
                { windowId: '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f', time: 0 },
                segments
            )
        ).toEqual(1)
    })

    it('throws when the player positions are not in the segment', () => {
        expect(() => {
            comparePlayerPositions(
                { windowId: '17da0b382b1165-00c767cd61e6e3-1c306851-13c680-17da0b382b210b', time: 100000000 },
                { windowId: '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f', time: 10000000 },
                segments
            )
        }).toThrow(`Could not find player positions in segments`)
    })
})

describe('getSegmentFromPlayerPosition', () => {
    it('matches a segment', () => {
        expect(
            getSegmentFromPlayerPosition(
                { windowId: '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f', time: 0 },
                segments
            )
        ).toEqual(segments[0])
    })

    it('returns null if it does not match', () => {
        expect(
            getSegmentFromPlayerPosition(
                { windowId: '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f', time: 100000000 },
                segments
            )
        ).toEqual(null)
    })
})

describe('getPlayerTimeFromPlayerPosition', () => {
    it('calculates the player time based on the player position', () => {
        expect(
            getPlayerTimeFromPlayerPosition(
                { windowId: '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f', time: 0 },
                segments
            )
        ).toEqual(0)
        expect(
            getPlayerTimeFromPlayerPosition(
                { windowId: '17da0b382b1165-00c767cd61e6e3-1c306851-13c680-17da0b382b210b', time: 4000 },
                segments
            )
        ).toEqual(44913)
        expect(
            getPlayerTimeFromPlayerPosition(
                { windowId: '17da0b382b1165-00c767cd61e6e3-1c306851-13c680-17da0b382b210b', time: 5000 },
                segments
            )
        ).toEqual(45913)
    })

    it('returns null if it does not find the position', () => {
        expect(
            getPlayerTimeFromPlayerPosition(
                { windowId: '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f', time: 100000000 },
                segments
            )
        ).toEqual(null)
    })
})

describe('getPlayerPositionFromPlayerTime', () => {
    it('calculates the player time based on the player position', () => {
        expect(getPlayerPositionFromPlayerTime(44913, segments)).toEqual({
            windowId: '17da0b382b1165-00c767cd61e6e3-1c306851-13c680-17da0b382b210b',
            time: 4000,
        })
        expect(getPlayerPositionFromPlayerTime(0, segments)).toEqual({
            windowId: '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f',
            time: 0,
        })
    })

    it('returns null if it does not find the player time', () => {
        expect(getPlayerPositionFromPlayerTime(10000000000, segments)).toEqual(null)
    })
})

describe('getPlayerPositionFromEpochTime', () => {
    it('calculates the player time based on the epoch time', () => {
        expect(
            getPlayerPositionFromEpochTime(
                1639078847000,
                '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f',
                metadata.startAndEndTimesByWindowId ?? {}
            )
        ).toEqual({ windowId: '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f', time: 227777 })
    })

    it('returns null if it does not find the player time', () => {
        expect(
            getPlayerPositionFromEpochTime(
                1739102187000,
                '17da0b382b1165-00c767cd61e6e3-1c306851-13c680-17da0b382b210b',
                metadata.startAndEndTimesByWindowId ?? {}
            )
        ).toEqual(null)
        expect(
            getPlayerPositionFromEpochTime(
                1739102187000,
                'b382b1165-00c767cd61e6e3-1c306851-13c680-17da0b382b210b',
                metadata.startAndEndTimesByWindowId ?? {}
            )
        ).toEqual(null)
    })
})

describe('guessPlayerPositionFromEpochTimeWithoutWindowId', () => {
    it('calculates the player time based on the epoch time', () => {
        expect(
            guessPlayerPositionFromEpochTimeWithoutWindowId(
                1639078847000,
                metadata.startAndEndTimesByWindowId,
                metadata.segments
            )
        ).toEqual({ windowId: '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f', time: 227777 })
    })

    it('returns null if the epoch time is outside the segment timebounds', () => {
        expect(
            guessPlayerPositionFromEpochTimeWithoutWindowId(
                1739102187000,
                metadata.startAndEndTimesByWindowId,
                metadata.segments
            )
        ).toEqual(null)
    })
})

describe('getEpochTimeFromPlayerPosition', () => {
    it('calculates epoch time based on the player position', () => {
        expect(
            getEpochTimeFromPlayerPosition(
                { windowId: '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f', time: 227777 },
                metadata.startAndEndTimesByWindowId ?? {}
            )
        ).toEqual(1639078847000)
    })

    it('returns null if it does not find the player position', () => {
        expect(
            getEpochTimeFromPlayerPosition(
                { windowId: '21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f', time: 227777 },
                metadata.startAndEndTimesByWindowId ?? {}
            )
        ).toEqual(null)
    })
})

describe('convertXToPlayerPosition', () => {
    it('calculates PlayerPosition based on x Value', () => {
        expect(convertXToPlayerPosition(50, 100, segments, 100000)).toEqual({
            time: 9087,
            windowId: '17da0b382b1165-00c767cd61e6e3-1c306851-13c680-17da0b382b210b',
        })
    })
})

describe('convertPlayerPositionToX', () => {
    it('calculates PlayerPosition based on x Value', () => {
        expect(
            convertPlayerPositionToX(
                { time: 9087, windowId: '17da0b382b1165-00c767cd61e6e3-1c306851-13c680-17da0b382b210b' },
                100,
                segments,
                100000
            )
        ).toEqual(50)
    })
})
