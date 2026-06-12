import { useActions, useValues } from 'kea'

import { keyForInsightLogicProps } from '@posthog/query-frontend/nodes/InsightViz/sharedUtils'
import { pathsDataLogic } from '@posthog/query-frontend/nodes/PathsQuery/pathsDataLogic'

import { PathItemFilters } from 'lib/components/PropertyFilters/PathItemFilters'

import { EditorFilterProps, EventPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

export function PathsExclusions({ insightProps }: EditorFilterProps): JSX.Element {
    const { pathsFilter, taxonomicGroupTypes } = useValues(pathsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(pathsDataLogic(insightProps))

    const { excludeEvents, pathGroupings } = pathsFilter || {}
    return (
        <PathItemFilters
            taxonomicGroupTypes={taxonomicGroupTypes}
            pageKey={`${keyForInsightLogicProps('new')(insightProps)}-excludeEvents`}
            propertyFilters={
                excludeEvents &&
                excludeEvents.map(
                    (name): EventPropertyFilter => ({
                        key: name,
                        value: name,
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Event,
                    })
                )
            }
            onChange={(values) => {
                updateInsightFilter({ excludeEvents: values.map((v) => v.value as string) })
            }}
            wildcardOptions={pathGroupings?.map((name) => ({ name }))}
        />
    )
}
