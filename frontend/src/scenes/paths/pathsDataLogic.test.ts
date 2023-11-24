import { expectLogic } from 'kea-test-utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { pathsDataLogic } from 'scenes/paths/pathsDataLogic'

import { initKeaTests } from '~/test/init'
import { InsightLogicProps, InsightType, PathType } from '~/types'

let logic: ReturnType<typeof pathsDataLogic.build>

const insightProps: InsightLogicProps = {
    dashboardItemId: undefined,
    cachedInsight: {
        filters: {
            insight: InsightType.PATHS,
        },
    },
}

async function initPathsDataLogic(): Promise<void> {
    logic = pathsDataLogic(insightProps)
    logic.mount()
    await expectLogic(logic).toFinishAllListeners()
}

describe('pathsDataLogic', () => {
    beforeEach(async () => {
        initKeaTests(false)
        await initPathsDataLogic()
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
