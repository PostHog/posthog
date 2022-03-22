import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { personsModalLogic } from './personsModalLogic'
import { router } from 'kea-router'

describe('personModalLogic', () => {
    let logic: ReturnType<typeof personsModalLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = personsModalLogic()
        logic.mount()
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
