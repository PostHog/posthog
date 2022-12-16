import { initKeaTests } from '~/test/init'
import { expectLogic } from 'kea-test-utils'
import { sharedListLogic } from 'scenes/session-recordings/player/inspector/sharedListLogic'
import { RecordingWindowFilter } from '~/types'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

const playerLogicProps = { sessionRecordingId: '1', playerKey: 'playlist' }

describe('sharedListLogic', () => {
    let logic: ReturnType<typeof sharedListLogic.build>

    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
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

    describe('miniFilters', () => {
        it('should start with the first entry selected', async () => {
            expect(logic.values.selectedMiniFilters).toEqual([
                'all-automatic',
                'console-all',
                'events-all',
                'performance-all',
            ])
        })

        it('should remove other selected filters if alone', async () => {
            logic.actions.setMiniFilter('all-errors', true)

            expect(logic.values.selectedMiniFilters.sort()).toEqual([
                'all-errors',
                'console-all',
                'events-all',
                'performance-all',
            ])
        })
    })
})
