import { useActions, useValues } from 'kea'

import { pathsLogic } from 'scenes/paths/pathsLogic'
import { pathsDataLogic } from 'scenes/paths/pathsDataLogic'

import {
    EditorFilterProps,
    EventPropertyFilter,
    PathsFilterType,
    PropertyFilterType,
    PropertyOperator,
    QueryEditorFilterProps,
} from '~/types'
import { PathItemFilters } from 'lib/components/PropertyFilters/PathItemFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

export function PathsExclusionsDataExploration({ insightProps }: QueryEditorFilterProps): JSX.Element {
    const { insightFilter, taxonomicGroupTypes } = useValues(pathsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(pathsDataLogic(insightProps))

    return (
        <PathsExclusionsComponent
            setFilter={updateInsightFilter}
            taxonomicGroupTypes={taxonomicGroupTypes}
            {...insightFilter}
        />
    )
}

export function PathsExclusions({ insightProps }: EditorFilterProps): JSX.Element {
    const { filter, taxonomicGroupTypes } = useValues(pathsLogic(insightProps))
    const { setFilter } = useActions(pathsLogic(insightProps))

    return <PathsExclusionsComponent setFilter={setFilter} taxonomicGroupTypes={taxonomicGroupTypes} {...filter} />
}

type PathsExclusionsComponentProps = {
    setFilter: (filter: PathsFilterType) => void
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
} & PathsFilterType

export function PathsExclusionsComponent({
    setFilter,
    exclude_events,
    path_groupings,
    taxonomicGroupTypes,
}: PathsExclusionsComponentProps): JSX.Element {
    return (
        <PathItemFilters
            taxonomicGroupTypes={taxonomicGroupTypes}
            pageKey="exclusion"
            propertyFilters={
                exclude_events &&
                exclude_events.map(
                    (name): EventPropertyFilter => ({
                        key: name,
                        value: name,
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Event,
                    })
                )
            }
            onChange={(values) => {
                setFilter({ exclude_events: values.map((v) => v.value as string) })
            }}
            wildcardOptions={path_groupings?.map((name) => ({ name }))}
        />
    )
}
