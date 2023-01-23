import { expectLogic } from 'kea-test-utils'
import { pathsDataLogic } from 'scenes/paths/pathsDataLogic'
import { InsightShortId, PathType } from '~/types'
import { initKeaTests } from '~/test/init'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

const Insight123 = '123' as InsightShortId

describe('pathsDataLogic', () => {
    let logic: ReturnType<typeof pathsDataLogic.build>
    const props = { dashboardItemId: Insight123 }
    beforeEach(() => {
        initKeaTests()
        logic = pathsDataLogic(props)
        logic.mount()
    })

    it('selects taxonomicGroupTypes from pathsFilter', async () => {
        await expectLogic(logic, () => {
            logic.actions.updateInsightFilter({
                include_event_types: [PathType.PageView, PathType.Screen, PathType.CustomEvent],
            })
        }).toMatchValues(logic, {
            taxonomicGroupTypes: [
                TaxonomicFilterGroupType.PageviewUrls,
                TaxonomicFilterGroupType.Screens,
                TaxonomicFilterGroupType.CustomEvents,
                TaxonomicFilterGroupType.Wildcards,
            ],
        })
    })
})
