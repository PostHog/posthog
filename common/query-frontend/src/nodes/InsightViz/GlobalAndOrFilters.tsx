import { useActions, useValues } from 'kea'

import { insightVizDataLogic } from '@posthog/query-frontend/nodes/InsightViz/insightVizDataLogic'
import { keyForInsightLogicProps } from '@posthog/query-frontend/nodes/InsightViz/sharedUtils'
import { ProductAnalyticsInsightQueryNode } from '@posthog/query-frontend/schema/schema-general'

import { getProjectEventExistence } from 'lib/utils/getAppContext'
import { getInsightPropertyFilterGroupTypes } from 'scenes/insights/utils/propertyTaxonomicGroupTypes'

import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { EditorFilterProps } from '~/types'

import { PropertyGroupFilters } from './PropertyGroupFilters/PropertyGroupFilters'
import { getAllEventNames } from './utils'

export function GlobalAndOrFilters({ insightProps }: EditorFilterProps): JSX.Element {
    const { actions: allActions } = useValues(actionsModel)
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const { querySource, hasDataWarehouseSeries } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))

    const { hasPageview, hasScreen } = getProjectEventExistence()

    const taxonomicGroupTypes = getInsightPropertyFilterGroupTypes({
        groupsTaxonomicTypes,
        hasPageview,
        hasScreen,
    })

    return (
        <PropertyGroupFilters
            insightProps={insightProps}
            pageKey={`${keyForInsightLogicProps('new')(insightProps)}-GlobalAndOrFilters`}
            query={querySource as ProductAnalyticsInsightQueryNode}
            setQuery={updateQuerySource}
            eventNames={getAllEventNames(querySource as ProductAnalyticsInsightQueryNode, allActions)}
            taxonomicGroupTypes={taxonomicGroupTypes}
            hasDataWarehouseSeries={hasDataWarehouseSeries}
        />
    )
}
