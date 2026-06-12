import { expectLogic } from 'kea-test-utils'

import { examples } from '@posthog/query-frontend/examples'
import { InsightVizNode, NodeKind } from '@posthog/query-frontend/schema/schema-general'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { pathsDataLogic } from 'scenes/paths-v2/pathsDataLogic'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'
import { InsightLogicProps, PathType } from '~/types'

let logic: ReturnType<typeof pathsDataLogic.build>

const insightProps: InsightLogicProps = {
    dashboardItemId: undefined,
    cachedInsight: {
        query: { kind: NodeKind.InsightVizNode, source: examples.InsightPathsQuery } as InsightVizNode,
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
        teamLogic.mount()
        await initPathsDataLogic()
    })

    it('selects taxonomicGroupTypes from pathsFilter', async () => {
        await expectLogic(logic, () => {
            logic.actions.updateInsightFilter({
                includeEventTypes: [PathType.PageView, PathType.Screen, PathType.CustomEvent],
            })
        })
            .toFinishAllListeners()
            .toMatchValues(logic, {
                taxonomicGroupTypes: [
                    TaxonomicFilterGroupType.PageviewUrls,
                    TaxonomicFilterGroupType.Screens,
                    TaxonomicFilterGroupType.CustomEvents,
                    TaxonomicFilterGroupType.Wildcards,
                ],
            })
    })
})
