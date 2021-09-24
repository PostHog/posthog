import { sessionRecordingsTableLogic } from './sessionRecordingsTableLogic'
import { sessionRecordingsTableLogicType } from './sessionRecordingsTableLogicType'
import { BuiltLogic } from 'kea'
import { mockAPI } from 'lib/api.mock'
import { expectLogic, initKeaTestLogic } from '~/test/kea-test-utils'

jest.mock('lib/api')

describe('sessionRecordingsTableLogic', () => {
    mockAPI(async ({ pathname, searchParams }) => {
        if (pathname === 'api/projects/@current/session_recordings' && searchParams['distinct_id'] === '') {
            return {
                results: ['List of recordings from server'],
            }
        } else if (
            pathname === 'api/projects/@current/session_recordings' &&
            searchParams['distinct_id'] === 'cool_user_99'
        ) {
            return {
                results: ["List of specific user's recordings from server"],
            }
        } else {
            throw new Error(`Unmocked fetch to: ${pathname} with params: ${JSON.stringify(searchParams)}`)
        }
    })

    describe('global logic', () => {
        let globalLogic: BuiltLogic<sessionRecordingsTableLogicType<string>>

        initKeaTestLogic({
            logic: sessionRecordingsTableLogic,
            onLogic: (l) => (globalLogic = l),
        })

        describe('core assumptions', () => {
            it('loads session recordings after mounting', async () => {
                await expectLogic(globalLogic)
                    .toDispatchActions(['getSessionRecordingsSuccess'])
                    .toMatchValues({ sessionRecordings: ['List of recordings from server'] })
            })
        })

        describe('sessionRecordingId', () => {
            it('starts as null', () => {
                expectLogic(globalLogic).toMatchValues({ sessionRecordingId: null })
            })
            it('is set by setSessionRecordingId and cleared by closeSessionPlayer', async () => {
                globalLogic.actions.setSessionRecordingId('abc')
                await expectLogic(globalLogic).toMatchValues({ sessionRecordingId: 'abc' })
                globalLogic.actions.closeSessionPlayer()
                await expectLogic(globalLogic).toMatchValues({ sessionRecordingId: null })
            })
        })
    })
    describe('person specific logic', () => {
        let personSpecificLogic: BuiltLogic<sessionRecordingsTableLogicType<string>>
        initKeaTestLogic({
            logic: sessionRecordingsTableLogic,
            props: {
                personIds: ['cool_user_99'],
            },
            onLogic: (l) => (personSpecificLogic = l),
        })

        it('loads session recordings for a specific user', async () => {
            await expectLogic(personSpecificLogic)
                .toDispatchActions(['getSessionRecordingsSuccess'])
                .toMatchValues({ sessionRecordings: ["List of specific user's recordings from server"] })
        })
    })
})
