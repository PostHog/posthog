import { expectLogic } from 'kea-test-utils'
import { defaultAPIMocks, mockAPI } from 'lib/api.mock'
import { initKeaTestLogic } from '~/test/init'
import { sessionRecordingLogic } from 'scenes/session-recordings/sessionRecordingLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { metaLogic } from 'scenes/session-recordings/player/metaLogic'

jest.mock('lib/api')

describe('metaLogic', () => {
    let logic: ReturnType<typeof metaLogic.build>

    mockAPI(async (url) => {
        return defaultAPIMocks(url)
    })

    initKeaTestLogic({
        logic: metaLogic,
        onLogic: (l) => (logic = l),
    })

    describe('core assumptions', () => {
        it('mounts other logics', async () => {
            await expectLogic(logic).toMount([sessionRecordingLogic, sessionRecordingPlayerLogic])
        })
    })
})
