import { defaultAPIMocks, mockAPI } from 'lib/api.mock'
import { expectLogic } from 'kea-test-utils'
import { initKeaTestLogic } from '~/test/init'
import { personsModalLogic } from './personsModalLogic'
import { router } from 'kea-router'
import { MatchedRecording } from '~/types'
jest.mock('lib/api')

describe('personModalLogic', () => {
    let logic: ReturnType<typeof personsModalLogic.build>

    mockAPI(defaultAPIMocks)

    initKeaTestLogic({
        logic: personsModalLogic,
        onLogic: (l) => (logic = l),
    })

    describe('sessionRecording', () => {
        it('by default is not set', () => {
            expectLogic(logic).toMatchValues({ sessionRecording: null })
            expect(router.values.hashParams.sessionRecording).toBeUndefined()
        })

        it('openRecordingModal sets the value and hash parameter', async () => {
            const recording = { session_id: 'abc', events: [] } as MatchedRecording
            await expectLogic(logic, () => {
                logic.actions.openRecordingModal(recording)
            }).toMatchValues({
                sessionRecording: recording,
            })
            expect(router.values.hashParams).toHaveProperty('sessionRecordingId', 'abc')
        })

        it('closeRecordingModal clears the value and hash parameter', async () => {
            await expectLogic(logic, () => {
                logic.actions.closeRecordingModal()
            }).toMatchValues({
                sessionRecording: null,
            })
            expect(router.values.hashParams.sessionRecordingId).toBeUndefined()
        })
    })
})
