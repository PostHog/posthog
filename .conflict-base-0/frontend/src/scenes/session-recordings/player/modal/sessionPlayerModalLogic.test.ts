import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { sessionPlayerModalLogic } from './sessionPlayerModalLogic'

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
    })
})
