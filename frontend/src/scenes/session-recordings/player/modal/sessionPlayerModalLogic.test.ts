import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { SessionPlayerModalRecordingList, sessionPlayerModalLogic } from './sessionPlayerModalLogic'

describe('sessionPlayerModalLogic', () => {
    let logic: ReturnType<typeof sessionPlayerModalLogic.build>
    const listOfSessionRecordings = [{ id: 'abc', viewed: false, recording_duration: 10 }]

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/session_recordings': [
                    200,
                    {
                        results: listOfSessionRecordings,
                    },
                ],
            },
        })
        initKeaTests()
        logic = sessionPlayerModalLogic()
        logic.mount()
    })
    describe('activeSessionRecording', () => {
        it('starts as null', () => {
            expectLogic(logic).toMatchValues({ activeSessionRecording: null })
        })
        it('is set by openSessionPlayer and cleared by closeSessionPlayer', () => {
            expectLogic(logic, () => logic.actions.openSessionPlayer({ id: 'abc' }))
                .toDispatchActions(['loadSessionRecordingsSuccess'])
                .toMatchValues({
                    selectedSessionRecording: { id: 'abc' },
                    activeSessionRecording: listOfSessionRecordings[0],
                })
            expect(router.values.hashParams).toHaveProperty('sessionRecordingId', 'abc')

            expectLogic(logic, () => logic.actions.closeSessionPlayer()).toMatchValues({
                activeSessionRecording: null,
            })
            expect(router.values.hashParams).not.toHaveProperty('sessionRecordingId')
        })

        it('is read from the URL on the session recording page', async () => {
            router.actions.push('/replay', { timestamp: 12345678 }, { sessionRecordingId: 'abc' })
            expect(router.values.hashParams).toHaveProperty('sessionRecordingId', 'abc')
            expect(router.values.searchParams).toHaveProperty('timestamp', 12345678)

            await expectLogic(logic).toDispatchActions([
                logic.actionCreators.openSessionPlayer({ id: 'abc' }, 12345678),
            ])
        })

        it('clears guided heatmap context when the player closes', () => {
            expectLogic(logic, () =>
                logic.actions.openSessionPlayer({ id: 'abc' }, null, {
                    type: 'heatmap-background-selection',
                    targetUrl: 'https://example.com/pricing',
                    matchingRecordingCount: 3,
                })
            ).toMatchValues({
                modalContext: {
                    type: 'heatmap-background-selection',
                    targetUrl: 'https://example.com/pricing',
                    matchingRecordingCount: 3,
                },
            })

            expectLogic(logic, () => logic.actions.closeSessionPlayer()).toMatchValues({ modalContext: null })
        })
    })

    describe('recording list', () => {
        const firstRecording = {
            id: 'first',
            matching_events: [
                { session_id: 'first', events: [{ uuid: 'event-1', timestamp: '2024-01-02T10:00:00Z' }] },
            ],
        }
        const secondRecording = {
            id: 'second',
            matching_events: [
                { session_id: 'second', events: [{ uuid: 'event-2', timestamp: '2024-01-02T11:00:00Z' }] },
            ],
        }
        const thirdRecording = { id: 'third' }

        const recordingList = (
            position: number,
            entryCount = 3,
            hasMoreToLoad = false
        ): SessionPlayerModalRecordingList => ({
            entries: [
                { sessionRecording: firstRecording, personDisplayName: 'Jane Doe' },
                { sessionRecording: secondRecording, personDisplayName: 'Jane Doe' },
                { sessionRecording: thirdRecording, personDisplayName: null },
            ].slice(0, entryCount),
            position,
            hasMoreToLoad,
        })

        it('moves to the next recording in the list from the beginning, with its own matching events', () => {
            logic.actions.openSessionPlayer(firstRecording, 12345678, null, recordingList(0))

            expectLogic(logic, () => logic.actions.playNextRecordingInList()).toMatchValues({
                activeSessionRecording: secondRecording,
                initialTimestamp: null,
                recordingList: recordingList(1),
                hasNextRecordingInList: true,
            })
            expect(router.values.hashParams).toHaveProperty('sessionRecordingId', 'second')
            expect(router.values.searchParams).not.toHaveProperty('timestamp')

            expectLogic(logic, () => logic.actions.playNextRecordingInList()).toMatchValues({
                activeSessionRecording: thirdRecording,
                recordingList: recordingList(2),
                hasNextRecordingInList: false,
            })

            logic.actions.playNextRecordingInList()
            expect(logic.values.activeSessionRecording).toEqual(thirdRecording)
        })

        it('clears the list when the player closes', () => {
            logic.actions.openSessionPlayer(secondRecording, null, null, recordingList(1))

            expectLogic(logic, () => logic.actions.closeSessionPlayer()).toMatchValues({
                recordingList: null,
                hasNextRecordingInList: false,
                showRecordingListPosition: false,
            })
        })

        it.each([
            { given: 'no list', list: null },
            { given: 'a list that holds another recording at its position', list: recordingList(0) },
        ])('opens without navigation when given $given', ({ list }) => {
            expectLogic(logic, () => logic.actions.openSessionPlayer(secondRecording, null, null, list)).toMatchValues({
                activeSessionRecording: secondRecording,
                recordingList: null,
                hasNextRecordingInList: false,
                showRecordingListPosition: false,
            })

            logic.actions.playNextRecordingInList()
            expect(logic.values.activeSessionRecording).toEqual(secondRecording)
        })

        it.each([
            { case: 'a single recording with every row loaded', entryCount: 1, hasMoreToLoad: false, expected: false },
            { case: 'a single recording with more rows to load', entryCount: 1, hasMoreToLoad: true, expected: true },
            { case: 'several recordings', entryCount: 3, hasMoreToLoad: false, expected: true },
        ])('showRecordingListPosition is $expected for $case', ({ entryCount, hasMoreToLoad, expected }) => {
            logic.actions.openSessionPlayer(firstRecording, null, null, recordingList(0, entryCount, hasMoreToLoad))

            expect(logic.values.showRecordingListPosition).toBe(expected)
        })
    })
})
