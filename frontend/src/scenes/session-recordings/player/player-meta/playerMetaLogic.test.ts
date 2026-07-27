import { expectLogic } from 'kea-test-utils'
import { HttpResponse } from 'msw'

import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { hasSummarizableEvents, playerMetaLogic } from 'scenes/session-recordings/player/player-meta/playerMetaLogic'
import { sessionRecordingDataCoordinatorLogic } from 'scenes/session-recordings/player/sessionRecordingDataCoordinatorLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { SessionRecordingType } from '~/types'

import recordingEventsJson from '../../__mocks__/recording_events_query'
import { recordingMetaJson } from '../../__mocks__/recording_meta'
import { snapshotsAsJSONLines } from '../../__mocks__/recording_snapshots'
import type { InspectorListItemEvent } from '../inspector/playerInspectorLogic'

jest.mock('../snapshot-processing/DecompressionWorkerManager')

const playerProps = { sessionRecordingId: '1', playerKey: 'playlist' }

describe('playerMetaLogic', () => {
    let logic: ReturnType<typeof playerMetaLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/session_recordings/:id': recordingMetaJson,
                '/api/environments/:team_id/session_recordings/:id/snapshots/': () =>
                    new HttpResponse(snapshotsAsJSONLines()),
            },
            post: {
                '/api/environments/:team_id/query/:kind': recordingEventsJson,
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        logic = playerMetaLogic(playerProps)
        logic.mount()
    })

    describe('core assumptions', () => {
        it('mounts other logics', () => {
            expectLogic(logic).toMount([
                sessionRecordingDataCoordinatorLogic(playerProps),
                sessionRecordingPlayerLogic(playerProps),
            ])
        })
        it('starts with loading state', () => {
            expectLogic(logic).toMatchValues({
                loading: true,
            })
        })
    })

    describe('loading state', () => {
        it('stops loading after meta load is successful', async () => {
            const session: SessionRecordingType = {
                id: '1',
            } as SessionRecordingType
            await expectLogic(logic, () => {
                sessionRecordingDataCoordinatorLogic(playerProps).actions.loadRecordingMeta()
                logic.actions.maybeLoadPropertiesForSessions([session])
            })
                .toDispatchActions(['loadRecordingMetaSuccess', 'loadPropertiesForSessionsSuccess'])
                .toMatchValues({ loading: false })
        })
    })

    describe('summaryDisabledReason', () => {
        it('returns an error string when events are not yet loaded', () => {
            expectLogic(logic).toMatchValues({
                summaryDisabledReason: expect.stringContaining('Session events are not available yet'),
            })
        })
    })

    describe('hasSummarizableEvents (gate mirrors backend filters)', () => {
        const start = dayjs('2026-01-01T00:00:00Z')
        const end = start.add(60, 'second')
        const makeEvent = (event: string, timestamp: typeof start): InspectorListItemEvent =>
            ({ type: 'events', timestamp, data: { event } }) as InspectorListItemEvent

        it('true for a normal event within the window', () => {
            expect(hasSummarizableEvents([makeEvent('$pageview', start.add(30, 'second'))], start, end)).toBe(true)
        })
        it('false when the only event is blocklisted ($feature_flag_called)', () => {
            expect(
                hasSummarizableEvents([makeEvent('$feature_flag_called', start.add(30, 'second'))], start, end)
            ).toBe(false)
        })
        it('false when the only event is within the start cutoff', () => {
            expect(hasSummarizableEvents([makeEvent('$pageview', start.add(2, 'second'))], start, end)).toBe(false)
        })
        it('false when the only event is within the end cutoff', () => {
            expect(hasSummarizableEvents([makeEvent('$pageview', end.subtract(2, 'second'))], start, end)).toBe(false)
        })
        it('true when at least one event survives the filters', () => {
            expect(
                hasSummarizableEvents(
                    [
                        makeEvent('$feature_flag_called', start.add(30, 'second')),
                        makeEvent('$pageview', start.add(2, 'second')),
                        makeEvent('custom_event', start.add(30, 'second')),
                    ],
                    start,
                    end
                )
            ).toBe(true)
        })
        it('applies the blocklist but skips the timing check when start/end are unknown', () => {
            expect(hasSummarizableEvents([makeEvent('$pageview', start)], null, null)).toBe(true)
            expect(hasSummarizableEvents([makeEvent('$feature_flag_called', start)], null, null)).toBe(false)
        })
    })
})
