import { useActions, useValues } from 'kea'
import { PathItemFilters } from 'lib/components/PropertyFilters/PathItemFilters'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { pathsDataLogic } from 'scenes/paths/pathsDataLogic'

import { EditorFilterProps, EventPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

export function PathsExclusions({ insightProps }: EditorFilterProps): JSX.Element {
    const { pathsFilter, taxonomicGroupTypes } = useValues(pathsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(pathsDataLogic(insightProps))

    const { exclude_events, path_groupings } = pathsFilter || {}
    return (
        <PathItemFilters
            taxonomicGroupTypes={taxonomicGroupTypes}
            pageKey={`${keyForInsightLogicProps('new')(insightProps)}-exclude_events`}
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
                updateInsightFilter({ exclude_events: values.map((v) => v.value as string) })
            }}
            wildcardOptions={path_groupings?.map((name) => ({ name }))}
        />
    )
}
