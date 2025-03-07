import { LemonCheckbox, LemonLabel } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { pathsV2DataLogic } from 'scenes/paths-v2/pathsV2DataLogic'

import { insightLogic } from '../insightLogic'
import { ActionFilter } from '../filters/ActionFilter/ActionFilter'
import { keyForInsightLogicProps } from '../sharedUtils'
import { useState } from 'react'
import { MathAvailability } from '../filters/ActionFilter/ActionFilterRow/ActionFilterRow'

// Keep in sync with defaults in schema
const DEFAULT_COLLAPE_EVENTS = true

export function PathsV2Steps(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { pathsV2Filter } = useValues(pathsV2DataLogic(insightProps))
    const { updateInsightFilter } = useActions(pathsV2DataLogic(insightProps))
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

    return (
        <>
            <ActionFilter
                bordered
                filters={actionFilters}
                setFilters={setActionFilters}
                typeKey={keyForInsightLogicProps('new')(insightProps)}
                mathAvailability={MathAvailability.None}
                // hideDeleteBtn={filterSteps.length === 1}
                // buttonCopy="Add step"
                // showSeriesIndicator={showSeriesIndicator}
                // seriesIndicatorType="numeric"
                // entitiesLimit={FUNNEL_STEP_COUNT_LIMIT}
                // sortable
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
