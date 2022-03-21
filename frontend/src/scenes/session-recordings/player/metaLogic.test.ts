import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { sessionRecordingLogic } from 'scenes/session-recordings/sessionRecordingLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { metaLogic } from 'scenes/session-recordings/player/metaLogic'
import recordingMetaJson from '../__mocks__/recording_meta.json'
import recordingEventsJson from '../__mocks__/recording_events.json'
import { useMocks } from '~/mocks/jest'

describe('metaLogic', () => {
    let logic: ReturnType<typeof metaLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/session_recordings/:id': { result: recordingMetaJson },
                '/api/projects/:team/events': { results: recordingEventsJson },
            },
        })
        initKeaTests()
        logic = metaLogic()
        logic.mount()
    })

    describe('core assumptions', () => {
        it('mounts other logics', () => {
            expectLogic(logic).toMount([sessionRecordingLogic, sessionRecordingPlayerLogic])
        })
        it('starts with loading state', () => {
            expectLogic(logic).toMatchValues({
                loading: true,
            })
        })
    })

    describe('loading state', () => {
        it('stops loading after meta load is successful', async () => {
            await expectLogic(logic, () => {
                sessionRecordingLogic.actions.loadRecordingMeta('1')
            })
                .toDispatchActions(['loadRecordingMetaSuccess'])
                .toMatchValues({ loading: false })
        })
    })
})
