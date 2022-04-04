import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { projectHomepageLogic } from './projectHomepageLogic'
import { router } from 'kea-router'
import { useMocks } from '~/mocks/jest'

describe('projectHomepageLogic', () => {
    let logic: ReturnType<typeof projectHomepageLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:team/session_recordings': () => [
                    200,
                    {
                        results: ['incoming recordings'],
                    },
                ],
            },
        })
        initKeaTests()
        logic = projectHomepageLogic()
        logic.mount()
    })

    describe('loadRecordings', () => {
        it('is called on mount and sets recordings', async () => {
            await expectLogic(logic)
                .toDispatchActions(['loadRecordings', 'loadRecordingsSuccess'])
                .toMatchValues({
                    recordings: ['incoming recordings'],
                })
        })
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
