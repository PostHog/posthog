import { useActions, useValues } from 'kea'
import { InfoCircleOutlined } from '@ant-design/icons'
import {
    dateOptionPlurals,
    dateOptions,
    retentionOptionDescriptions,
    retentionOptions,
    retentionTableLogic,
} from 'scenes/retention/retentionTableLogic'
import { EditorFilterProps, FilterType, QueryEditorFilterProps, RetentionType } from '~/types'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { ActionFilter } from '../filters/ActionFilter/ActionFilter'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { AggregationSelectComponent } from 'scenes/insights/filters/AggregationSelect'
import { groupsModel } from '~/models/groupsModel'
import { MathAvailability } from '../filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { Link } from 'lib/lemon-ui/Link'
import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

export function RetentionSummaryDataExploration({ insightProps }: QueryEditorFilterProps): JSX.Element {
    return <RetentionSummary insightProps={insightProps} />
}

export function RetentionSummary({ insightProps }: EditorFilterProps): JSX.Element {
    const { showGroupsOptions } = useValues(groupsModel)
    const { filters, actionFilterTargetEntity, actionFilterReturningEntity } = useValues(
        retentionTableLogic(insightProps)
    )
    const { setFilters } = useActions(retentionTableLogic(insightProps))

    return (
        <div className="space-y-2" data-attr="retention-summary">
            <div className="flex items-center">
                Show
                {showGroupsOptions ? (
                    <AggregationSelectComponent
                        className="mx-2"
                        aggregationGroupTypeIndex={filters.aggregation_group_type_index}
                        onChange={(groupTypeIndex) => setFilters({ aggregation_group_type_index: groupTypeIndex })}
                    />
                ) : (
                    <b> Unique users </b>
                )}
                who performed
            </div>
            <div className="flex items-center">
                event or action
                <ActionFilter
                    entitiesLimit={1}
                    mathAvailability={MathAvailability.None}
                    hideFilter
                    hideRename
                    buttonCopy="Add graph series"
                    filters={actionFilterTargetEntity as FilterType} // retention filters use target and returning entity instead of events
                    setFilters={(newFilters: FilterType) => {
                        if (newFilters.events && newFilters.events.length > 0) {
                            setFilters({ target_entity: newFilters.events[0] })
                        } else if (newFilters.actions && newFilters.actions.length > 0) {
                            setFilters({ target_entity: newFilters.actions[0] })
                        } else {
                            setFilters({ target_entity: undefined })
                        }
                    }}
                    typeKey="retention-table"
                />
                <LemonSelect
                    options={Object.entries(retentionOptions).map(([key, value]) => ({
                        label: value,
                        value: key,
                        element: (
                            <>
                                {value}
                                <Tooltip placement="right" title={retentionOptionDescriptions[key]}>
                                    <InfoCircleOutlined className="info-indicator" />
                                </Tooltip>
                            </>
                        ),
                    }))}
                    value={filters.retention_type ? retentionOptions[filters.retention_type] : undefined}
                    onChange={(value): void => setFilters({ retention_type: value as RetentionType })}
                    dropdownMatchSelectWidth={false}
                />
            </div>
            <div className="flex items-center">
                in the last
                <LemonInput
                    type="number"
                    className="ml-2 w-20"
                    value={(filters.total_intervals ?? 11) - 1}
                    onChange={(value) => setFilters({ total_intervals: (value || 0) + 1 })}
                />
                <LemonSelect
                    className="mx-2"
                    value={filters.period}
                    onChange={(value): void => setFilters({ period: value ? value : undefined })}
                    options={dateOptions.map((period) => ({
                        value: period,
                        label: dateOptionPlurals[period] || period,
                    }))}
                    dropdownMatchSelectWidth={false}
                />
                and then came back to perform
            </div>
            <div className="flex items-center">
                event or action
                <ActionFilter
                    entitiesLimit={1}
                    mathAvailability={MathAvailability.None}
                    hideFilter
                    hideRename
                    buttonCopy="Add graph series"
                    filters={actionFilterReturningEntity as FilterType}
                    setFilters={(newFilters: FilterType) => {
                        if (newFilters.events && newFilters.events.length > 0) {
                            setFilters({ returning_entity: newFilters.events[0] })
                        } else if (newFilters.actions && newFilters.actions.length > 0) {
                            setFilters({ returning_entity: newFilters.actions[0] })
                        } else {
                            setFilters({ returning_entity: undefined })
                        }
                    }}
                    typeKey="retention-table-returning"
                />
                on any of the next {dateOptionPlurals[filters.period ?? 'Day']}.
            </div>
            <div>
                <p className="text-muted mt-4">
                    Want to learn more about retention?{' '}
                    <Link
                        to="https://posthog.com/docs/features/retention?utm_campaign=learn-more-horizontal&utm_medium=in-product"
                        target="_blank"
                        className="inline-flex items-center"
                    >
                        Go to docs
                        <IconOpenInNew className="ml-2" />
                    </Link>
                </p>
            </div>
        </div>
    )
}
