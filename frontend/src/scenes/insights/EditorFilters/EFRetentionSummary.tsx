import React from 'react'
import { useActions, useValues } from 'kea'
import { InfoCircleOutlined } from '@ant-design/icons'
import {
    dateOptionPlurals,
    dateOptions,
    retentionOptionDescriptions,
    retentionOptions,
    retentionTableLogic,
} from 'scenes/retention/retentionTableLogic'
import { Input, Select } from 'antd'
import { EditorFilterProps, FilterType, RetentionType } from '~/types'
import { IconOpenInNew } from 'lib/components/icons'
import { ActionFilter } from '../ActionFilter/ActionFilter'
import { Tooltip } from 'lib/components/Tooltip'
import { AggregationSelect } from 'scenes/insights/AggregationSelect'
import { groupsModel } from '~/models/groupsModel'
import { MathAvailability } from '../ActionFilter/ActionFilterRow/ActionFilterRow'

export function EFRetentionSummary({ insightProps }: EditorFilterProps): JSX.Element {
    const { showGroupsOptions } = useValues(groupsModel)
    const { filters, actionFilterTargetEntity, actionFilterReturningEntity } = useValues(
        retentionTableLogic(insightProps)
    )
    const { setFilters } = useActions(retentionTableLogic(insightProps))

    return (
        <div className="space-y-05" data-attr="retention-summary">
            <div>
                Show{' '}
                {showGroupsOptions ? (
                    <AggregationSelect
                        aggregationGroupTypeIndex={filters.aggregation_group_type_index}
                        onChange={(groupTypeIndex) => setFilters({ aggregation_group_type_index: groupTypeIndex })}
                    />
                ) : (
                    <b>Unique users</b>
                )}{' '}
                who performed event or action
            </div>
            <div className="flex-center">
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
                <Select
                    value={filters.retention_type ? retentionOptions[filters.retention_type] : undefined}
                    onChange={(value): void => setFilters({ retention_type: value as RetentionType })}
                    dropdownMatchSelectWidth={false}
                >
                    {Object.entries(retentionOptions).map(([key, value]) => (
                        <Select.Option key={key} value={key}>
                            {value}
                            <Tooltip placement="right" title={retentionOptionDescriptions[key]}>
                                <InfoCircleOutlined className="info-indicator" />
                            </Tooltip>
                        </Select.Option>
                    ))}
                </Select>
            </div>
            <div>
                in the last{' '}
                <Input
                    type="tel" /* type="tel" shows a numpad on a phone, and hides the undebouncable up/down arrows you get with "number" */
                    style={{ width: 80 }}
                    value={String((filters.total_intervals ?? 11) - 1)}
                    onChange={(e) => setFilters({ total_intervals: parseInt(e.target.value) + 1 })}
                />{' '}
                <Select
                    value={filters.period}
                    onChange={(value): void => setFilters({ period: value })}
                    dropdownMatchSelectWidth={false}
                >
                    {dateOptions.map((period) => (
                        <Select.Option key={period} value={period}>
                            {dateOptionPlurals[period] || period}
                        </Select.Option>
                    ))}
                </Select>
            </div>
            <div>
                and then came back to perform event or action{' '}
                <div className="flex">
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
                </div>
                on any of the next {dateOptionPlurals[filters.period ?? 'Day']}
            </div>

            <div>
                <p className="text-muted mt">
                    Want to learn more about retention?{' '}
                    <a
                        href="https://posthog.com/docs/features/retention?utm_campaign=learn-more-horizontal&utm_medium=in-product"
                        target="_blank"
                        rel="noopener"
                        style={{ display: 'inline-flex', alignItems: 'center' }}
                    >
                        Go to docs
                        <IconOpenInNew style={{ marginLeft: 4 }} />
                    </a>
                </p>
            </div>
        </div>
    )
}
