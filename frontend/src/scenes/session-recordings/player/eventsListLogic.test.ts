import { initKeaTestLogic } from '~/test/init'
import { eventsListLogic } from 'scenes/session-recordings/player/eventsListLogic'
import { expectLogic } from 'kea-test-utils'
import { sessionRecordingLogic } from 'scenes/session-recordings/sessionRecordingLogic'

describe('eventsListLogic', () => {
    let logic: ReturnType<typeof eventsListLogic.build>

    initKeaTestLogic({
        logic: eventsListLogic,
        onLogic: (l) => (logic = l),
    })

    describe('core assumptions', () => {
        it('mounts other logics', async () => {
            await expectLogic(logic).toMount([sessionRecordingLogic])
        })
    })

    describe('setLocalFilter', () => {
        it('calls setFilter in parent logic with debounce', async () => {
            const filters = { query: 'mini pretzels' }
            await expectLogic(logic, () => {
                logic.actions.setLocalFilters({ query: 'no mini pretzels' })
                logic.actions.setLocalFilters(filters)
            })
                .toDispatchActions([sessionRecordingLogic.actionCreators.setFilters(filters)])
                .toNotHaveDispatchedActions([sessionRecordingLogic.actionCreators.setFilters(filters)])
        })
    })
})
