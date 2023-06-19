import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { expectLogic } from 'kea-test-utils'
import { sessionRecordingsListPropertiesLogic } from 'scenes/session-recordings/playlist/sessionRecordingsListPropertiesLogic'

describe('sessionRecordingsListPropertiesLogic', () => {
    let logic: ReturnType<typeof sessionRecordingsListPropertiesLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/session_recordings/properties': {
                    results: [
                        { id: 's1', properties: { blah: 'blah1' } },
                        { id: 's2', properties: { blah: 'blah2' } },
                    ],
                },
            },
        })
        initKeaTests()
    })

    beforeEach(() => {
        logic = sessionRecordingsListPropertiesLogic()
        logic.mount()
    })

    it('loads properties', async () => {
        const nextSessionIds = ['1', '2', '3']

        await expectLogic(logic, async () => {
            logic.actions.loadPropertiesForSessions(nextSessionIds)
        }).toDispatchActions(['loadPropertiesForSessionsSuccess'])

        expect(logic.values).toMatchObject({
            recordingProperties: [
                { id: 's1', properties: { blah: 'blah1' } },
                { id: 's2', properties: { blah: 'blah2' } },
            ],
            recordingPropertiesById: {
                s1: { blah: 'blah1' },
                s2: { blah: 'blah2' },
            },
        })
    })

    it('does not loads cached properties', async () => {
        const nextSessionIds = ['1', '2', '3']

        await expectLogic(logic, async () => {
            logic.actions.loadPropertiesForSessions(nextSessionIds)
        }).toDispatchActions(['loadPropertiesForSessionsSuccess'])

        expect(logic.values).toMatchObject({
            recordingPropertiesById: {
                s1: { blah: 'blah1' },
                s2: { blah: 'blah2' },
            },
        })

        await expectLogic(logic, async () => {
            logic.actions.maybeLoadPropertiesForSessions(nextSessionIds)
        }).toNotHaveDispatchedActions(['loadPropertiesForSessionsSuccess'])

        expect(logic.values).toMatchObject({
            recordingPropertiesById: {
                s1: { blah: 'blah1' },
                s2: { blah: 'blah2' },
            },
        })
    })
})
