import { sessionRecordingsTableLogic } from './sessionRecordingsTableLogic'
import { sessionRecordingsTableLogicType } from './sessionRecordingsTableLogicType'
import { BuiltLogic } from 'kea'
import { mockAPI } from 'lib/api.mock'
import { expectLogic, initKeaTestLogic } from '~/test/kea-test-utils'

jest.mock('lib/api')

describe('sessionRecordingsTableLogic', () => {
    let logic: BuiltLogic<sessionRecordingsTableLogicType<string>>

    mockAPI(async ({ pathname, searchParams }) => {
        if (pathname === 'api/projects/@current/session_recordings' && searchParams['distinct_id'] === '') {
            return {
                results: ['List of recordings from server'],
            }
        } else if (pathname === 'api/projects/@current/session_recordings' && searchParams['distinct_id'] !== '') {
            return {
                results: ["List of specific user's recordings from server"],
            }
        } else {
            throw new Error(`Unmocked fetch to: ${pathname} with params: ${JSON.stringify(searchParams)}`)
        }
    })

    initKeaTestLogic({
        logic: sessionRecordingsTableLogic,
        onLogic: (l) => (logic = l),
    })

    describe('core assumptions', () => {
        it('loads session recordings after mounting', async () => {
            await expectLogic(logic)
                .toDispatchActions(['getSessionRecordingsSuccess'])
                .toMatchValues({ sessionRecordings: ['List of recordings from server'] })
        })
    })

    describe('sessionRecordingId', () => {
        it('starts as null', () => {
            expectLogic(logic).toMatchValues({ sessionRecordingId: null })
        })
        it('is set by setSessionRecordingId and cleared by closeSessionPlayer', async () => {
            logic.actions.setSessionRecordingId('abc')
            await expectLogic(logic).toMatchValues({ sessionRecordingId: 'abc' })
            logic.actions.closeSessionPlayer()
            await expectLogic(logic).toMatchValues({ sessionRecordingId: null })
        })
    })

    initKeaTestLogic({
        logic: sessionRecordingsTableLogic,
        props: {
            personIds: ['abc'],
        },
        onLogic: (l) => (logic = l),
    })

    describe('logic with distinct_id param', () => {
        it('loads session recordings for a specific user', async () => {
            await expectLogic(logic)
                .toDispatchActions(['getSessionRecordingsSuccess'])
                .toMatchValues({ sessionRecordings: ["List of specific user's recordings from server"] })
        })
    })
})
