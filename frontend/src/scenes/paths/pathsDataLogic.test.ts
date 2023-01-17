import { expectLogic } from 'kea-test-utils'
import { pathsDataLogic } from 'scenes/paths/pathsDataLogic'
import { InsightShortId, PathType } from '~/types'
import { initKeaTests } from '~/test/init'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'

const Insight123 = '123' as InsightShortId

describe('pathsDataLogic', () => {
    let logic: ReturnType<typeof pathsDataLogic.build>

    describe('syncs with insightDataLogic', () => {
        const props = { dashboardItemId: Insight123 }
        beforeEach(() => {
            initKeaTests()
            logic = pathsDataLogic(props)
            logic.mount()
        })

        it('setIncludeEventTypes updates includedEventTypes and pathsFilter', async () => {
            await expectLogic(logic, () => {
                logic.actions.setIncludeEventTypes([PathType.Screen, PathType.PageView])
            })
                .toMatchValues(logic, {
                    includeEventTypes: [PathType.Screen, PathType.PageView],
                })
                .toMatchValues(insightDataLogic(props), {
                    insightFilter: expect.objectContaining({
                        include_event_types: [PathType.Screen, PathType.PageView],
                    }),
                })
        })
    })
})
