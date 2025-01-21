import { IconInfo } from '@posthog/icons'
import { LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { AggregationSelect } from 'scenes/insights/filters/AggregationSelect'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import {
    dateOptionPlurals,
    dateOptions,
    retentionOptionDescriptions,
    retentionOptions,
} from 'scenes/retention/constants'

import { groupsModel } from '~/models/groupsModel'
import { isInsightQueryNode } from '~/queries/utils'
import { EditorFilterProps, FilterType, RetentionType } from '~/types'

import { ActionFilter } from '../filters/ActionFilter/ActionFilter'
import { MathAvailability } from '../filters/ActionFilter/ActionFilterRow/ActionFilterRow'

export function Retention2025({ insightProps }: EditorFilterProps): JSX.Element | null {
    const {
        showGroupsOptions,
        // groupsTaxonomicTypes
    } = useValues(groupsModel)
    const { retentionFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const {
        targetEntity,
        returningEntity,
        retentionType,
        // totalIntervals,
        period,
    } = retentionFilter || {}

    const { querySource } = useValues(insightVizDataLogic(insightProps))

    if (!isInsightQueryNode(querySource)) {
        return null
    }

    // const filters = queryNodeToFilter(querySource)

    // const propertiesTaxonomicGroupTypes = [
    //     TaxonomicFilterGroupType.EventProperties,
    //     TaxonomicFilterGroupType.PersonProperties,
    //     TaxonomicFilterGroupType.EventFeatureFlags,
    //     ...groupsTaxonomicTypes,
    //     TaxonomicFilterGroupType.Cohorts,
    //     TaxonomicFilterGroupType.Elements,
    //     TaxonomicFilterGroupType.SessionProperties,
    //     TaxonomicFilterGroupType.HogQLExpression,
    //     TaxonomicFilterGroupType.DataWarehouseProperties,
    //     TaxonomicFilterGroupType.DataWarehousePersonProperties,
    // ]

    return (
        <>
            <div className="space-y-3" data-attr="retention-summary">
                <div className="flex items-center">
                    For
                    {showGroupsOptions ? (
                        <AggregationSelect className="mx-2" insightProps={insightProps} hogqlAvailable={false} />
                    ) : (
                        <b> Unique users </b>
                    )}
                </div>
                <div>who performed</div>
                <ActionFilter
                    entitiesLimit={1}
                    mathAvailability={MathAvailability.None}
                    hideRename
                    filters={{ events: [targetEntity] } as FilterType} // retention filters use target and returning entity instead of events
                    setFilters={(newFilters: FilterType) => {
                        if (newFilters.events && newFilters.events.length > 0) {
                            updateInsightFilter({ targetEntity: newFilters.events[0] })
                        } else if (newFilters.actions && newFilters.actions.length > 0) {
                            updateInsightFilter({ targetEntity: newFilters.actions[0] })
                        } else {
                            updateInsightFilter({ targetEntity: undefined })
                        }
                    }}
                    typeKey={`${keyForInsightLogicProps('new')(insightProps)}-targetEntity`}
                />
                <LemonSelect
                    options={Object.entries(retentionOptions).map(([key, value]) => ({
                        label: value,
                        value: key,
                        element: (
                            <>
                                {value}
                                <Tooltip placement="right" title={retentionOptionDescriptions[key]}>
                                    <IconInfo className="info-indicator" />
                                </Tooltip>
                            </>
                        ),
                    }))}
                    value={retentionType ? retentionOptions[retentionType] : undefined}
                    onChange={(value): void => updateInsightFilter({ retentionType: value as RetentionType })}
                    dropdownMatchSelectWidth={false}
                />

                <div>and then returned to perform</div>
                <ActionFilter
                    entitiesLimit={1}
                    mathAvailability={MathAvailability.None}
                    hideRename
                    buttonCopy="Add graph series"
                    filters={{ events: [returningEntity] } as FilterType}
                    setFilters={(newFilters: FilterType) => {
                        if (newFilters.events && newFilters.events.length > 0) {
                            updateInsightFilter({ returningEntity: newFilters.events[0] })
                        } else if (newFilters.actions && newFilters.actions.length > 0) {
                            updateInsightFilter({ returningEntity: newFilters.actions[0] })
                        } else {
                            updateInsightFilter({ returningEntity: undefined })
                        }
                    }}
                    typeKey={`${keyForInsightLogicProps('new')(insightProps)}-returningEntity`}
                />
                <div className="flex items-center gap-2">
                    <div>on any of the next</div>
                    <LemonSelect
                        value={period}
                        onChange={(value): void => updateInsightFilter({ period: value ? value : undefined })}
                        options={dateOptions.map((period) => ({
                            value: period,
                            label: dateOptionPlurals[period] || period,
                        }))}
                        dropdownMatchSelectWidth={false}
                    />
                </div>
            </div>
        </>
    )
}
