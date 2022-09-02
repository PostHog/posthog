import { initKeaTests } from '~/test/init'
import { expectLogic } from 'kea-test-utils'
import { sharedListLogic } from 'scenes/session-recordings/player/list/sharedListLogic'
import { RecordingWindowFilter } from '~/types'

const playerLogicProps = { sessionRecordingId: '1', playerKey: 'playlist' }

describe('sharedListLogic', () => {
    let logic: ReturnType<typeof sharedListLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = sharedListLogic(playerLogicProps)
        logic.mount()
    })

    describe('setWindowIdFilter', () => {
        it('happy case', async () => {
            await expectLogic(logic).toMatchValues({
                windowIdFilter: RecordingWindowFilter.All,
            })
            await expectLogic(logic, () => {
                logic.actions.setWindowIdFilter('nightly')
            })
                .toDispatchActions(['setWindowIdFilter'])
                .toMatchValues({
                    windowIdFilter: 'nightly',
                })
        })
        it('default all', async () => {
            await expectLogic(logic, () => {
                logic.actions.setWindowIdFilter(null as unknown as string)
            })
                .toDispatchActions(['setWindowIdFilter'])
                .toMatchValues({
                    windowIdFilter: RecordingWindowFilter.All,
                })
        })
    })
})
