import { defaultAPIMocks, mockAPI } from 'lib/api.mock'
import { expectLogic } from 'kea-test-utils'
import { initKeaTestLogic } from '~/test/init'
import { personsModalLogic } from './personsModalLogic'
import { router } from 'kea-router'

jest.mock('lib/api')

describe('personModalLogic', () => {
    let logic: ReturnType<typeof personsModalLogic.build>

    mockAPI(defaultAPIMocks)

    initKeaTestLogic({
        logic: personsModalLogic,
        onLogic: (l) => (logic = l),
    })

    describe('sessionRecordingId', () => {
        it('by default is not set', () => {
            expectLogic(logic).toMatchValues({ sessionRecordingId: null })
            expect(router.values.hashParams.sessionRecordingId).toBeUndefined()
        })

        it('openRecordingModal sets the value and hash parameter', async () => {
            await expectLogic(logic, () => {
                logic.actions.openRecordingModal('abc')
            }).toMatchValues({
                sessionRecordingId: 'abc',
            })
            expect(router.values.hashParams).toHaveProperty('sessionRecordingId', 'abc')
        })

        it('closeRecordingModal clears the value and hash parameter', async () => {
            await expectLogic(logic, () => {
                logic.actions.closeRecordingModal()
            }).toMatchValues({
                sessionRecordingId: null,
            })
            expect(router.values.hashParams.sessionRecordingId).toBeUndefined()
        })
    })
})
