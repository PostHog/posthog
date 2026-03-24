import { useActions, useValues } from 'kea'

import { getProjectEventExistence } from 'lib/utils/getAppContext'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { getInsightPropertyFilterGroupTypes } from 'scenes/insights/utils/propertyTaxonomicGroupTypes'

import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { ProductAnalyticsInsightQueryNode } from '~/queries/schema/schema-general'
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
