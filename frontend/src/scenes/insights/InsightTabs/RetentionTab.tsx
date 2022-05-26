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
import { Col, Input, Row, Select } from 'antd'
import { ChartDisplayType, FilterType, PropertyGroupFilter, RetentionType } from '~/types'
import './RetentionTab.scss'
import { FEATURE_FLAGS } from 'lib/constants'
import useBreakpoint from 'antd/lib/grid/hooks/useBreakpoint'
import { IconOpenInNew } from 'lib/components/icons'
import { ActionFilter } from '../ActionFilter/ActionFilter'
import { Tooltip } from 'lib/components/Tooltip'
import { insightLogic } from 'scenes/insights/insightLogic'
import { AggregationSelect } from 'scenes/insights/AggregationSelect'
import { groupsModel } from '~/models/groupsModel'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { BreakdownFilter } from '../BreakdownFilter'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { PropertyGroupFilters } from 'lib/components/PropertyGroupFilters/PropertyGroupFilters'
import { convertPropertiesToPropertyGroup } from 'lib/utils'
import { MathAvailability } from '../ActionFilter/ActionFilterRow/ActionFilterRow'

export function RetentionTab(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { insightProps, allEventNames } = useValues(insightLogic)
    const { groupsTaxonomicTypes, showGroupsOptions } = useValues(groupsModel)
    const { filters, actionFilterTargetEntity, actionFilterReturningEntity } = useValues(
        retentionTableLogic(insightProps)
    )
    const { setFilters } = useActions(retentionTableLogic(insightProps))

    const screens = useBreakpoint()
    const isSmallScreen = screens.xs || (screens.sm && !screens.md)

    return (
        <div data-attr="retention-tab" className="retention-tab">
            <Row gutter={24}>
                <Col md={12} xs={24}>
                    <Row gutter={8} align="middle">
                        <Col>Show</Col>
                        <Col>
                            {showGroupsOptions ? (
                                <AggregationSelect
                                    aggregationGroupTypeIndex={filters.aggregation_group_type_index}
                                    onChange={(groupTypeIndex) =>
                                        setFilters({ aggregation_group_type_index: groupTypeIndex })
                                    }
                                />
                            ) : (
                                <b>Unique users</b>
                            )}
                        </Col>
                        <Col>who performed event or action</Col>
                        <Col>
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
                        </Col>
                        <Col>
                            <div style={{ display: '-webkit-inline-box', flexWrap: 'wrap' }}>
                                <Select
                                    value={
                                        filters.retention_type ? retentionOptions[filters.retention_type] : undefined
                                    }
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
                        </Col>
                        <Col>in the last</Col>
                        <Col>
                            <Input
                                type="tel" /* type="tel" shows a numpad on a phone, and hides the undebouncable up/down arrows you get with "number" */
                                style={{ width: 80 }}
                                value={String((filters.total_intervals ?? 11) - 1)}
                                onChange={(e) => setFilters({ total_intervals: parseInt(e.target.value) + 1 })}
                            />
                        </Col>
                        <Col>
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
                        </Col>
                        <Col>and then came back to perform event or action</Col>
                        <Col>
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
                        </Col>
                        <Col>on any of the next {dateOptionPlurals[filters.period ?? 'Day']}</Col>
                    </Row>
                    <Row>
                        <Col>
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
                        </Col>
                    </Row>
                </Col>
                <Col md={12} xs={24} style={{ marginTop: isSmallScreen ? '2rem' : 0 }}>
                    <PropertyGroupFilters
                        value={convertPropertiesToPropertyGroup(filters.properties)}
                        onChange={(properties: PropertyGroupFilter) => {
                            setFilters({ properties })
                        }}
                        taxonomicGroupTypes={[
                            TaxonomicFilterGroupType.EventProperties,
                            TaxonomicFilterGroupType.PersonProperties,
                            ...groupsTaxonomicTypes,
                            TaxonomicFilterGroupType.Cohorts,
                            TaxonomicFilterGroupType.Elements,
                        ]}
                        pageKey="insight-retention"
                        eventNames={allEventNames}
                        filters={filters}
                        setTestFilters={(testFilters) => setFilters(testFilters)}
                    />

                    {featureFlags[FEATURE_FLAGS.RETENTION_BREAKDOWN] &&
                    filters.display !== ChartDisplayType.ActionsLineGraph ? (
                        <>
                            <hr />
                            <h4 className="secondary">
                                Breakdown by
                                <Tooltip
                                    placement="right"
                                    title="Use breakdown to see the aggregation (total volume, active users, etc.) for each value of that property. For example, breaking down by Current URL with total volume will give you the event volume for each URL your users have visited."
                                >
                                    <InfoCircleOutlined className="info-indicator" />
                                </Tooltip>
                            </h4>
                            <Row align="middle">
                                <BreakdownFilter filters={filters} setFilters={setFilters} useMultiBreakdown />
                            </Row>
                        </>
                    ) : null}
                </Col>
            </Row>
        </div>
    )
}
