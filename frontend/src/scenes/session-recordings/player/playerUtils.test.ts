import { RecordingSegment } from '~/types'
import { parseMetadataResponse } from './sessionRecordingDataLogic'
import recordingMetaJson from '../__mocks__/recording_meta.json'
import {
    comparePlayerPositions,
    getPlayerPositionFromPlayerTime,
    getPlayerTimeFromPlayerPosition,
    getSegmentFromPlayerPosition,
} from './playerUtils'

const metadata = parseMetadataResponse(recordingMetaJson)
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
