import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import { RecordingWatchedSource } from 'lib/utils/eventUsageLogic'
import { initKeaTests } from '~/test/init'
import { sessionRecordingDataLogic } from './player/sessionRecordingDataLogic'
import { sessionPlayerDrawerLogic } from './sessionPlayerDrawerLogic'

describe('sessionPlayerDrawerLogic', () => {
    let logic: ReturnType<typeof sessionPlayerDrawerLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = sessionPlayerDrawerLogic()
        logic.mount()
    })
    describe('activeSessionRecordingId', () => {
        it('starts as null', () => {
            expectLogic(logic).toMatchValues({ activeSessionRecordingId: null })
        })
        it('is set by openSessionPlayer and cleared by closeSessionPlayer', async () => {
            expectLogic(logic, () =>
                logic.actions.openSessionPlayer('abc', RecordingWatchedSource.RecordingsList)
            ).toMatchValues({
                activeSessionRecordingId: 'abc',
            })
            expect(router.values.hashParams).toHaveProperty('sessionRecordingId', 'abc')

            expectLogic(logic, () => logic.actions.closeSessionPlayer()).toMatchValues({
                activeSessionRecordingId: null,
            })
            expect(router.values.hashParams).not.toHaveProperty('sessionRecordingId')
        })

        it('is read from the URL on the session recording page', async () => {
            router.actions.push('/recordings', {}, { sessionRecordingId: 'recording1212' })
            expect(router.values.hashParams).toHaveProperty('sessionRecordingId', 'recording1212')

            await expectLogic(logic)
                .toDispatchActions(['openSessionPlayer'])
                .toMatchValues({ activeSessionRecordingId: 'recording1212' })
        })
    })
    describe('sessionRecordingDataLogic', () => {
        it('is mounted when a new recording is opened and starts loading', async () => {
            expectLogic(logic, () => logic.actions.openSessionPlayer('abc', RecordingWatchedSource.RecordingsList))
                .toMount([sessionRecordingDataLogic({ sessionRecordingId: 'abc' })])
                .toDispatchActions(['loadEntireRecording'])
        })
    })
})
