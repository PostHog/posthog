import { useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { actionsModel } from '~/models/actionsModel'
import { PropertyGroupFilters } from '~/queries/nodes/InsightViz/PropertyGroupFilters/PropertyGroupFilters'
import { getAllEventNames } from '~/queries/nodes/InsightViz/utils'
import { ReplayQuery } from '~/queries/schema'

export default function HogQLFilters({
    query,
    setQuery,
}: {
    query: ReplayQuery
    setQuery: (node: ReplayQuery) => void
}): JSX.Element {
    const { actions: allActions } = useValues(actionsModel)

    const taxonomicGroupTypes = [
        TaxonomicFilterGroupType.SessionProperties,
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.PersonProperties,
        TaxonomicFilterGroupType.Cohorts,
        TaxonomicFilterGroupType.Actions,
    ]

    return (
        <div className="HogQLFilters">
            <PropertyGroupFilters
                query={query}
                setQuery={setQuery}
                eventNames={getAllEventNames(query, allActions)}
                pageKey="session-replay"
                taxonomicGroupTypes={taxonomicGroupTypes}
            />
        </div>
    )
}
