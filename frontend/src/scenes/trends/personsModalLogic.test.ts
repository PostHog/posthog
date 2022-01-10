import { BuiltLogic } from 'kea'
import { defaultAPIMocks, mockAPI } from 'lib/api.mock'
import { expectLogic } from 'kea-test-utils'
import { initKeaTestLogic } from '~/test/init'
import { LoadPeopleFromUrlProps, personsModalLogic, PersonsModalParams } from './personsModalLogic'
import { personsModalLogicType } from './personsModalLogicType'
import { router } from 'kea-router'

jest.mock('lib/api')

describe('personModalLogic', () => {
    let logic: BuiltLogic<personsModalLogicType<LoadPeopleFromUrlProps, PersonsModalParams>>

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
