import React from 'react'
import { useValues, useActions } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { InfoCircleOutlined } from '@ant-design/icons'
import { retentionTableLogic, dateOptions, retentionOptionDescriptions } from 'scenes/retention/retentionTableLogic'
import { Select, Row, Col } from 'antd'
import { FilterType, RetentionType } from '~/types'
import { TestAccountFilter } from '../TestAccountFilter'
import './RetentionTab.scss'
import { ACTIONS_LINE_GRAPH_LINEAR, FEATURE_FLAGS, RETENTION_FIRST_TIME, RETENTION_RECURRING } from 'lib/constants'
import useBreakpoint from 'antd/lib/grid/hooks/useBreakpoint'
import { IconOpenInNew } from 'lib/components/icons'
import { GlobalFiltersTitle } from '../common'
import { ActionFilter } from '../ActionFilter/ActionFilter'
import { Tooltip } from 'lib/components/Tooltip'
import { insightLogic } from 'scenes/insights/insightLogic'
import { AggregationSelect } from 'scenes/insights/AggregationSelect'
import { groupsModel } from '~/models/groupsModel'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { BreakdownFilter } from '../BreakdownFilter'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

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

    // TODO: Update constant in retentionTableLogic.ts when releasing 4050
    const retentionOptions = {
        [`${RETENTION_FIRST_TIME}`]: 'for the first time',
        [`${RETENTION_RECURRING}`]: 'recurringly',
    }

    return (
        <div data-attr="retention-tab" className="retention-tab">
            <Row gutter={16}>
                <Col md={16} xs={24}>
                    <Row gutter={8} align="middle">
                        <Col>
                            <ActionFilter
                                horizontalUI
                                singleFilter
                                hideMathSelector
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
                                customRowPrefix={
                                    <>
                                        Showing{' '}
                                        {showGroupsOptions ? (
                                            <AggregationSelect
                                                aggregationGroupTypeIndex={filters.aggregation_group_type_index}
                                                onChange={(groupTypeIndex) =>
                                                    setFilters({ aggregation_group_type_index: groupTypeIndex })
                                                }
                                            />
                                        ) : (
                                            <b>Unique users</b>
                                        )}{' '}
                                        who did
                                    </>
                                }
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
                        <Col>grouped by</Col>
                        <Col>
                            <Select
                                value={filters.period}
                                onChange={(value): void => setFilters({ period: value })}
                                dropdownMatchSelectWidth={false}
                            >
                                {dateOptions.map((period) => (
                                    <Select.Option key={period} value={period}>
                                        {period}
                                    </Select.Option>
                                ))}
                            </Select>
                        </Col>
                    </Row>
                    <Row gutter={8} align="middle" className="mt">
                        <Col>
                            <ActionFilter
                                horizontalUI
                                singleFilter
                                hideMathSelector
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
                                customRowPrefix="... who then came back and did"
                            />
                        </Col>
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
                <Col md={8} xs={24} style={{ marginTop: isSmallScreen ? '2rem' : 0 }}>
                    <GlobalFiltersTitle unit="actions/events" />
                    <PropertyFilters
                        propertyFilters={filters.properties}
                        onChange={(properties) => setFilters({ properties })}
                        pageKey="insight-retention"
                        taxonomicGroupTypes={[
                            TaxonomicFilterGroupType.EventProperties,
                            TaxonomicFilterGroupType.PersonProperties,
                            ...groupsTaxonomicTypes,
                            TaxonomicFilterGroupType.Cohorts,
                            TaxonomicFilterGroupType.Elements,
                        ]}
                        eventNames={allEventNames}
                    />
                    <TestAccountFilter filters={filters} onChange={setFilters} />

                    {featureFlags[FEATURE_FLAGS.RETENTION_BREAKDOWN] &&
                    filters.display !== ACTIONS_LINE_GRAPH_LINEAR ? (
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
