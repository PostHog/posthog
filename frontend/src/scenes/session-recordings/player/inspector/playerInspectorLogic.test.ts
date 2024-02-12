import { expectLogic } from 'kea-test-utils'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { playerInspectorLogic } from 'scenes/session-recordings/player/inspector/playerInspectorLogic'

import { initKeaTests } from '~/test/init'

const playerLogicProps = { sessionRecordingId: '1', playerKey: 'playlist' }

describe('playerInspectorLogic', () => {
    let logic: ReturnType<typeof playerInspectorLogic.build>

    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        logic = playerInspectorLogic(playerLogicProps)
        logic.mount()
    })

    describe('setWindowIdFilter', () => {
        it('happy case', async () => {
            await expectLogic(logic).toMatchValues({
                windowIdFilter: null,
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
                    windowIdFilter: null,
                })
        })
    })
})
