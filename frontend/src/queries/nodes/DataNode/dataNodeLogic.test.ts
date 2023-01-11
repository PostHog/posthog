import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { expectLogic } from 'kea-test-utils'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'

describe('dataNodeLogic', () => {
    let logic: ReturnType<typeof dataNodeLogic.build>

    describe('opt-in prompts', () => {
        beforeEach(async () => {
            useMocks({
                patch: {
                    // '/api/prompts/my_prompts/': configOptIn,
                },
            })
            initKeaTests()
            featureFlagLogic.mount()
            logic = dataNodeLogic()
            logic.mount()
            await expectLogic(logic).toMount([dataNodeLogic])
        })

        afterEach(() => logic.unmount())

        it('calls query to fetch data', async () => {})
        it('requests again when changing the props query', async () => {})
        it('does not do a request when only changing query objects by reference', async () => {})
        it('clears the response if changing the query type', async () => {})
        it('can load new data if EventsQuery sorted by timestamp', async () => {})
        it('can autoload new data for EventsQuery', async () => {})
        it('will highlight new rows for EventsQuery', async () => {})
        it('can load next data for EventsQuery', async () => {})
        it('can load next data for PersonsNode', async () => {})
    })
})
