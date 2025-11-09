import { LemonCheckbox, LemonLabel } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useState } from 'react'
import { pathsV2DataLogic } from 'scenes/paths-v2/pathsV2DataLogic'

import { ActionFilter } from '../filters/ActionFilter/ActionFilter'
import { MathAvailability } from '../filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { insightLogic } from '../insightLogic'
import { keyForInsightLogicProps } from '../sharedUtils'
import { FilterType } from '~/types'
import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { PathsV2Query } from '~/queries/schema'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'

// Keep in sync with defaults in schema
const DEFAULT_COLLAPE_EVENTS = false

export function PathsV2Steps(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { pathsV2Filter, querySource } = useValues(pathsV2DataLogic(insightProps))
    const { updateInsightFilter, updateQuerySource } = useActions(pathsV2DataLogic(insightProps))
    const [actionFilters, setActionFilters] = useState({})

    const { collapseEvents } = pathsV2Filter || {}

    // <div className="mt-4 space-y-4">
    //     {showGroupsOptions && (
    //         <div className="flex items-center w-full gap-2">
    //             <span>Aggregating by</span>
    //             <AggregationSelect insightProps={insightProps} hogqlAvailable />
    //         </div>
    //     )}

    //     <FunnelConversionWindowFilter insightProps={insightProps} />
    // </div>

    // const actionFilters = {}

    //         const filters = queryNodeToFilter(querySource)

    // filters = { filters }
    //                 setFilters={(payload: Partial<FilterType>): void => {
    //                     updateQuerySource({ series: actionsAndEventsToSeries(payload as any, true, mathAvailability) } as
    //                         | TrendsQuery
    //                         | FunnelsQuery
    //                         | StickinessQuery
    //                         | LifecycleQuery)
    //                 }}
    console.debug('querySource', querySource)

    return (
        <>
            <ActionFilter
                // bordered
                // filters={actionFilters}
                // setFilters={setActionFilters}

                filters={queryNodeToFilter(querySource)}
                setFilters={(payload: Partial<FilterType>): void => {
                    updateQuerySource({
                        series: actionsAndEventsToSeries(payload as any, true, MathAvailability.None),
                    } as PathsV2Query)
                }}
                typeKey={keyForInsightLogicProps('new')(insightProps)}
                mathAvailability={MathAvailability.None}
                // hideDeleteBtn={filterSteps.length === 1}
                // buttonCopy="Add step"
                // showSeriesIndicator={showSeriesIndicator}
                // seriesIndicatorType="numeric"
                // entitiesLimit={FUNNEL_STEP_COUNT_LIMIT}
                entitiesLimit={2}
                // sortable
                //             addFilterDefaultOptions
                // buttonCopy?: string
                // buttonType?: LemonButtonProps['type']
                // buttonProps?: LemonButtonProps
                // /** Hides the rename option */
                // hideRename?: boolean
                // /** Hides the duplicate option */
                // hideDuplicate?: boolean
                hideRename
                hideDuplicate
                showNestedArrow
                // propertiesTaxonomicGroupTypes={[
                //     TaxonomicFilterGroupType.EventProperties,
                //     TaxonomicFilterGroupType.PersonProperties,
                //     TaxonomicFilterGroupType.EventFeatureFlags,
                //     ...groupsTaxonomicTypes,
                //     TaxonomicFilterGroupType.Cohorts,
                //     TaxonomicFilterGroupType.Elements,
                //     TaxonomicFilterGroupType.SessionProperties,
                //     TaxonomicFilterGroupType.HogQLExpression,
                // ]}
            />
            <LemonCheckbox
                checked={collapseEvents != null ? collapseEvents : DEFAULT_COLLAPE_EVENTS}
                onChange={() => updateInsightFilter({ collapseEvents: !collapseEvents })}
                fullWidth
                label="Remove repeated events"
                bordered
            />
        </>
    )
}
