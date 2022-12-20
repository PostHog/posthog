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
        logic = sessionRecordingsListPropertiesLogic({ key: 'test', sessionIds: [] })
        logic.mount()
    })

    describe('core', () => {
        it('loads properties when sessionIds prop changes', () => {
            const nextSessionIds = ['1', '2', '3']

            expectLogic(logic, async () => {
                sessionRecordingsListPropertiesLogic({ key: 'test', sessionIds: nextSessionIds }).mount()
            })
                .toMatchValues({
                    sessionRecordingsPropertiesResponse: {
                        results: [],
                    },
                })
                .toDispatchActions([
                    logic.actionCreators.getSessionRecordingsProperties(nextSessionIds),
                    'getSessionRecordingsPropertiesSuccess',
                ])
                .toMatchValues({
                    sessionRecordingsPropertiesResponse: {
                        results: [
                            { id: 's1', properties: { blah: 'blah1' } },
                            { id: 's2', properties: { blah: 'blah2' } },
                        ],
                    },
                    sessionRecordingIdToProperties: {
                        s1: { blah: 'blah1' },
                        s2: { blah: 'blah2' },
                    },
                })
        })
    })
})
