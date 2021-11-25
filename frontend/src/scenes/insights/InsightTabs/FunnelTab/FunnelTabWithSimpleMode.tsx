import React, { useEffect } from 'react'
import { useValues, useActions, useMountedLogic } from 'kea'

import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { ActionFilter } from '../../ActionFilter/ActionFilter'
import { Button, Card, Col, Row, Tag } from 'antd'
import { useState } from 'react'
import { funnelCommandLogic } from './funnelCommandLogic'
import { InfoCircleOutlined } from '@ant-design/icons'
import { ToggleButtonChartFilter } from './ToggleButtonChartFilter'
import { Tooltip } from 'lib/components/Tooltip'
import useBreakpoint from 'antd/lib/grid/hooks/useBreakpoint'
import { GlobalFiltersTitle } from 'scenes/insights/common'
import { PropertyFilters } from 'lib/components/PropertyFilters'
import { isValidPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { TestAccountFilter } from 'scenes/insights/TestAccountFilter'
import { FunnelStepReference, FunnelVizType, StepOrderValue } from '~/types'
import { BreakdownFilter } from 'scenes/insights/BreakdownFilter'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { groupsModel } from '~/models/groupsModel'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { AggregationSelect } from 'scenes/insights/AggregationSelect'
import { IconArrowDropDown } from 'lib/components/icons'
import clsx from 'clsx'
import { FunnelConversionWindowFilter } from './FunnelConversionWindowFilter'
import { FunnelStepOrderPicker } from './FunnelStepOrderPicker'
import { FunnelExclusionsFilter } from './FunnelExclusionsFilter'
import { FunnelStepReferencePicker } from './FunnelStepReferencePicker'

export function FunnelTabWithSimpleMode(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { loadResults } = useActions(insightLogic)
    const {
        isStepsEmpty,
        filters,
        clickhouseFeaturesEnabled,
        aggregationTargetLabel,
        filterSteps,
        advancedOptionsUsedCount,
    } = useValues(funnelLogic(insightProps))
    const { clearFunnel, setFilters, toggleAdvancedMode, setStepReference } = useActions(funnelLogic(insightProps))
    const { featureFlags } = useValues(featureFlagLogic)
    const { groupsTaxonomicTypes, showGroupsOptions } = useValues(groupsModel)
    const screens = useBreakpoint()
    const isHorizontalUIEnabled = featureFlags[FEATURE_FLAGS.FUNNEL_HORIZONTAL_UI]
    const isSmallScreen = screens.xs || (screens.sm && !screens.md) || (screens.xl && !isHorizontalUIEnabled)
    useMountedLogic(funnelCommandLogic)

    return (
        <Row gutter={16} data-attr="funnel-tab" className="funnel-tab">
            <Col xs={24} md={16} xl={isHorizontalUIEnabled ? undefined : 24}>
                <div style={{ paddingRight: isSmallScreen ? undefined : 16 }}>
                    <form
                        onSubmit={(e): void => {
                            e.preventDefault()
                            loadResults()
                        }}
                    >
                        <Row className="mb-05" justify="space-between" align="middle">
                            <h4 className="secondary" style={{ marginBottom: 0 }}>
                                Query steps
                            </h4>
                            {clickhouseFeaturesEnabled && (
                                <div className="flex-center">
                                    <span
                                        style={{
                                            marginRight: 6,
                                            textTransform: 'none',
                                            fontWeight: 'normal',
                                            color: 'var(--muted)',
                                        }}
                                    >
                                        Graph type
                                    </span>
                                    <ToggleButtonChartFilter simpleMode />
                                </div>
                            )}
                        </Row>
                        <Card className="action-filters-bordered" bodyStyle={{ padding: 0 }}>
                            <ActionFilter
                                filters={filters}
                                setFilters={setFilters}
                                typeKey={`EditFunnel-action`}
                                hideMathSelector={true}
                                hideDeleteBtn={filterSteps.length === 1}
                                buttonCopy="Add step"
                                buttonType="link"
                                showSeriesIndicator={!isStepsEmpty}
                                seriesIndicatorType="numeric"
                                fullWidth
                                sortable
                                showNestedArrow={true}
                                propertiesTaxonomicGroupTypes={[
                                    TaxonomicFilterGroupType.EventProperties,
                                    TaxonomicFilterGroupType.PersonProperties,
                                    ...groupsTaxonomicTypes,
                                    TaxonomicFilterGroupType.Cohorts,
                                    TaxonomicFilterGroupType.Elements,
                                ]}
                                rowClassName="action-filters-bordered"
                            />
                            <div className="mb-05" />
                            {!clickhouseFeaturesEnabled && (
                                <>
                                    <hr style={{ margin: '0', marginBottom: '0.5rem' }} />
                                    <Row style={{ justifyContent: 'flex-end', paddingBottom: 8, paddingRight: 8 }}>
                                        {!isStepsEmpty && (
                                            <Button
                                                type="link"
                                                onClick={(): void => clearFunnel()}
                                                data-attr="save-funnel-clear-button"
                                            >
                                                Clear
                                            </Button>
                                        )}
                                        <CalculateFunnelButton style={{ marginLeft: 4 }} />
                                    </Row>
                                </>
                            )}
                        </Card>
                    </form>
                </div>
                {showGroupsOptions && (
                    <>
                        <Row className="mt" style={{ paddingRight: isSmallScreen ? undefined : 16 }}>
                            <div className="flex-center text-muted" style={{ width: '100%' }}>
                                <span style={{ marginRight: 4 }}>Aggregating by</span>
                                <AggregationSelect
                                    aggregationGroupTypeIndex={filters.aggregation_group_type_index}
                                    onChange={(newValue) => {
                                        setFilters({ aggregation_group_type_index: newValue })
                                    }}
                                />
                            </div>
                        </Row>
                    </>
                )}
                <div className="text-muted">
                    <FunnelConversionWindowFilter horizontal />
                </div>
            </Col>
            <Col xs={24} md={8} xl={isHorizontalUIEnabled ? undefined : 24}>
                <hr />
                <div className="mt" />
                <div className="flex-center">
                    <div style={{ flexGrow: 1 }}>
                        <GlobalFiltersTitle unit="steps" />
                    </div>
                    <div style={{ marginBottom: '0.5rem' }}>
                        <TestAccountFilter filters={filters} onChange={setFilters} />
                    </div>
                </div>
                <PropertyFilters
                    pageKey={`EditFunnel-property`}
                    propertyFilters={filters.properties || []}
                    onChange={(anyProperties) => {
                        setFilters({
                            properties: anyProperties.filter(isValidPropertyFilter),
                        })
                    }}
                    taxonomicGroupTypes={[
                        TaxonomicFilterGroupType.EventProperties,
                        TaxonomicFilterGroupType.PersonProperties,
                        ...groupsTaxonomicTypes,
                        TaxonomicFilterGroupType.Cohorts,
                        TaxonomicFilterGroupType.Elements,
                    ]}
                />

                {clickhouseFeaturesEnabled && filters.funnel_viz_type === FunnelVizType.Steps && (
                    <>
                        <hr />
                        <h4 className="secondary">
                            Breakdown
                            <Tooltip
                                placement="right"
                                title="Use breakdown to see the aggregation (total volume, active users, etc.) for each value of that property. For example, breaking down by Current URL with total volume will give you the event volume for each URL your users have visited."
                            >
                                <InfoCircleOutlined className="info-indicator" />
                            </Tooltip>
                        </h4>
                        <Row align="middle">
                            <BreakdownFilter filters={filters} setFilters={setFilters} buttonType="default" />
                        </Row>
                    </>
                )}

                {clickhouseFeaturesEnabled && (
                    <>
                        <hr />
                        <div className="flex-center cursor-pointer" onClick={toggleAdvancedMode}>
                            <h4 className="secondary" style={{ flexGrow: 1 }}>
                                Advanced options{' '}
                                {!filters.funnel_advanced && !!advancedOptionsUsedCount && (
                                    <Tag className="lemonade-tag">{advancedOptionsUsedCount}</Tag>
                                )}
                            </h4>
                            <div>
                                <div
                                    className={clsx('advanced-options-dropdown', filters.funnel_advanced && 'expanded')}
                                >
                                    <IconArrowDropDown />
                                </div>
                            </div>
                        </div>
                        {filters.funnel_advanced ? (
                            <div className="funnel-advanced-options">
                                <div className="mb-05">
                                    Step order
                                    <Tooltip
                                        title={
                                            <ul style={{ paddingLeft: '1.2rem' }}>
                                                <li>
                                                    <b>Sequential</b> - Step B must happen after Step A, but any number
                                                    events can happen between A and B.
                                                </li>
                                                <li>
                                                    <b>Strict Order</b> - Step B must happen directly after Step A
                                                    without any events in between.
                                                </li>
                                                <li>
                                                    <b>Any Order</b> - Steps can be completed in any sequence.
                                                </li>
                                            </ul>
                                        }
                                    >
                                        <InfoCircleOutlined className="info-indicator" style={{ marginRight: 4 }} />
                                    </Tooltip>
                                </div>
                                <FunnelStepOrderPicker />
                                <div className="mt">Conversion rate calculation</div>
                                <FunnelStepReferencePicker bordered />
                                <div className="mt">
                                    Exclusion steps
                                    <Tooltip
                                        title={
                                            <>
                                                Exclude {aggregationTargetLabel.plural} who completed the specified
                                                event between two specific steps. Note that these
                                                {aggregationTargetLabel.plural} will be{' '}
                                                <b>completely excluded from the entire funnel</b>.
                                            </>
                                        }
                                    >
                                        <InfoCircleOutlined className="info-indicator" />
                                    </Tooltip>
                                </div>
                                <div className="funnel-exclusions-filter">
                                    <FunnelExclusionsFilter />
                                </div>
                                {!!advancedOptionsUsedCount && (
                                    <div>
                                        <Button
                                            type="link"
                                            style={{ color: 'var(--danger)', paddingLeft: 0, marginTop: 16 }}
                                            onClick={() => {
                                                setStepReference(FunnelStepReference.total)
                                                setFilters({
                                                    funnel_order_type: StepOrderValue.ORDERED,
                                                    exclusions: [],
                                                })
                                            }}
                                        >
                                            Reset advanced options
                                        </Button>
                                    </div>
                                )}
                            </div>
                        ) : (
                            <div className="text-muted-alt cursor-pointer" onClick={toggleAdvancedMode}>
                                Exclude events between steps, custom conversion limit window and allow any step
                                ordering.
                            </div>
                        )}
                    </>
                )}
            </Col>
        </Row>
    )
}

function CalculateFunnelButton({ style }: { style: React.CSSProperties }): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { filters, areFiltersValid, filtersDirty, clickhouseFeaturesEnabled, isLoading } = useValues(
        funnelLogic(insightProps)
    )
    const [tooltipOpen, setTooltipOpen] = useState(false)
    const shouldRecalculate = filtersDirty && areFiltersValid && !isLoading && !clickhouseFeaturesEnabled

    // Only show tooltip after 3s of inactivity
    useEffect(() => {
        if (shouldRecalculate) {
            const rerenderInterval = setTimeout(() => {
                setTooltipOpen(true)
            }, 3000)

            return () => {
                clearTimeout(rerenderInterval)
                setTooltipOpen(false)
            }
        } else {
            setTooltipOpen(false)
        }
    }, [shouldRecalculate, filters])

    return (
        <Tooltip
            visible={tooltipOpen}
            title="Your query has changed. Calculate your changes to see updates in the visualization."
        >
            <Button
                style={style}
                type={shouldRecalculate ? 'primary' : 'default'}
                htmlType="submit"
                disabled={!areFiltersValid}
                data-attr="save-funnel-button"
            >
                Calculate
            </Button>
        </Tooltip>
    )
}
