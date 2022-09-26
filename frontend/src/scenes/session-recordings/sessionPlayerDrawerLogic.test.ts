import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { sessionPlayerDrawerLogic } from './sessionPlayerDrawerLogic'

describe('sessionPlayerDrawerLogic', () => {
    let logic: ReturnType<typeof sessionPlayerDrawerLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = sessionPlayerDrawerLogic()
        logic.mount()
    })
    describe('activeSessionRecording', () => {
        it('starts as null', () => {
            expectLogic(logic).toMatchValues({ activeSessionRecording: null })
        })
        it('is set by openSessionPlayer and cleared by closeSessionPlayer', async () => {
            expectLogic(logic, () => logic.actions.openSessionPlayer({ id: 'abc' })).toMatchValues({
                activeSessionRecording: { id: 'abc' },
            })
            expect(router.values.hashParams).toHaveProperty('sessionRecordingId', 'abc')

            expectLogic(logic, () => logic.actions.closeSessionPlayer()).toMatchValues({
                activeSessionRecording: null,
            })
            expect(router.values.hashParams).not.toHaveProperty('sessionRecordingId')
        })

        it('is read from the URL on the session recording page', async () => {
            router.actions.push('/recordings', {}, { sessionRecording: { id: 'recording1212' } })
            expect(router.values.hashParams).toHaveProperty('sessionRecordingId', 'recording1212')

            await expectLogic(logic)
                .toDispatchActions(['openSessionPlayer'])
                .toMatchValues({ activeSessionRecording: { id: 'recording1212' } })
        })
    })
})
