import { sessionRecordingsTableLogic } from './sessionRecordingsTableLogic'
import { sessionRecordingsTableLogicType } from './sessionRecordingsTableLogicType'
import { BuiltLogic } from 'kea'
import { mockAPI } from 'lib/api.mock'
import { expectLogic, initKeaTestLogic } from '~/test/kea-test-utils'
import { router } from 'kea-router'

jest.mock('lib/api')

describe('sessionRecordingsTableLogic', () => {
    let logic: BuiltLogic<sessionRecordingsTableLogicType<string>>

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
            it('is set by openSessionPlayer and cleared by closeSessionPlayer', async () => {
                expectLogic(logic, () => logic.actions.openSessionPlayer('abc')).toMatchValues({
                    sessionRecordingId: 'abc',
                })
                expect(router.values.searchParams).toHaveProperty('sessionRecordingId', 'abc')

                expectLogic(logic, () => logic.actions.closeSessionPlayer()).toMatchValues({ sessionRecordingId: null })
                expect(router.values.searchParams).not.toHaveProperty('sessionRecordingId')
            })

            it('is read from the URL on the session recording page', async () => {
                router.actions.push('/session_recordings', { sessionRecordingId: 'recording1212' })
                expect(router.values.searchParams).toHaveProperty('sessionRecordingId', 'recording1212')

                await expectLogic(logic)
                    .toDispatchActions(['openSessionPlayer'])
                    .toMatchValues({ sessionRecordingId: 'recording1212' })
            })
        })
    })
    describe('person specific logic', () => {
        initKeaTestLogic({
            logic: sessionRecordingsTableLogic,
            props: {
                distinctId: 'cool_user_99',
            },
            onLogic: (l) => (logic = l),
        })

        it('loads session recordings for a specific user', async () => {
            await expectLogic(logic)
                .toDispatchActions(['getSessionRecordingsSuccess'])
                .toMatchValues({ sessionRecordings: ["List of specific user's recordings from server"] })
        })

        it('reads sessionRecordingId from the URL on the person page', async () => {
            router.actions.push('/person/123', { sessionRecordingId: 'recording1212' })
            expect(router.values.searchParams).toHaveProperty('sessionRecordingId', 'recording1212')

            await expectLogic(logic)
                .toDispatchActions(['openSessionPlayer'])
                .toMatchValues({ sessionRecordingId: 'recording1212' })
        })
    })
})
