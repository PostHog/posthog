import { expectLogic } from 'kea-test-utils'
import { mockAPI, MOCK_TEAM_ID } from 'lib/api.mock'
import { initKeaTests } from '~/test/init'
import { sessionRecordingLogic } from 'scenes/session-recordings/sessionRecordingLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { metaLogic } from 'scenes/session-recordings/player/metaLogic'
import recordingMetaJson from '../__mocks__/recording_meta.json'
import recordingEventsJson from '../__mocks__/recording_events.json'

jest.mock('lib/api')
const EVENTS_SESSION_RECORDING_META_ENDPOINT = `api/projects/${MOCK_TEAM_ID}/session_recordings`
const EVENTS_SESSION_RECORDING_EVENTS_ENDPOINT = `api/projects/${MOCK_TEAM_ID}/events`

describe('metaLogic', () => {
    let logic: ReturnType<typeof metaLogic.build>

    mockAPI(async ({ pathname }) => {
        if (pathname.startsWith(EVENTS_SESSION_RECORDING_META_ENDPOINT)) {
            return { result: recordingMetaJson }
        } else if (pathname.startsWith(EVENTS_SESSION_RECORDING_EVENTS_ENDPOINT)) {
            return { results: recordingEventsJson }
        }
    })

    beforeEach(() => {
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
