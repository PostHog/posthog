import React, { useEffect } from 'react'
import { useValues, useActions, useMountedLogic } from 'kea'

import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { ActionFilter } from '../../ActionFilter/ActionFilter'
import { Button, Col, Row } from 'antd'
import { useState } from 'react'
import { SaveModal } from '../../SaveModal'
import { funnelCommandLogic } from './funnelCommandLogic'
import { InfoCircleOutlined } from '@ant-design/icons'
import { ToggleButtonChartFilter } from './ToggleButtonChartFilter'
import { Tooltip } from 'lib/components/Tooltip'
import { FunnelStepOrderPicker } from 'scenes/insights/InsightTabs/FunnelTab/FunnelStepOrderPicker'
import useBreakpoint from 'antd/lib/grid/hooks/useBreakpoint'
import { GlobalFiltersTitle } from 'scenes/insights/common'
import { PropertyFilters } from 'lib/components/PropertyFilters'
import { isValidPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { TestAccountFilter } from 'scenes/insights/TestAccountFilter'
import { FunnelVizType } from '~/types'
import { BreakdownFilter } from 'scenes/insights/BreakdownFilter'
import { FunnelConversionWindowFilter } from 'scenes/insights/InsightTabs/FunnelTab/FunnelConversionWindowFilter'
import { FunnelExclusionsFilter } from 'scenes/insights/InsightTabs/FunnelTab/FunnelExclusionsFilter'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { AggregationSelect } from 'scenes/insights/AggregationSelect'
import { groupsModel } from '~/models/groupsModel'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FunnelTabWithSimpleMode } from './FunnelTabWithSimpleMode'

export function FunnelTab(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    return featureFlags[FEATURE_FLAGS.FUNNEL_SIMPLE_MODE] ? <FunnelTabWithSimpleMode /> : <FunnelTabOld />
}

function FunnelTabOld(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { loadResults } = useActions(insightLogic)
    const { isStepsEmpty, filters, clickhouseFeaturesEnabled, aggregationTargetLabel, filterSteps } = useValues(
        funnelLogic(insightProps)
    )
    const { clearFunnel, setFilters, saveFunnelInsight } = useActions(funnelLogic(insightProps))
    const { featureFlags } = useValues(featureFlagLogic)
    const { groupsTaxonomicTypes, showGroupsOptions } = useValues(groupsModel)
    const [savingModal, setSavingModal] = useState<boolean>(false)
    const screens = useBreakpoint()
    const isHorizontalUIEnabled = featureFlags[FEATURE_FLAGS.FUNNEL_HORIZONTAL_UI]
    const isSmallScreen = screens.xs || (screens.sm && !screens.md) || (screens.xl && !isHorizontalUIEnabled)
    useMountedLogic(funnelCommandLogic)

    const closeModal = (): void => setSavingModal(false)
    const onSubmit = (input: string): void => {
        saveFunnelInsight(input)
        closeModal()
    }

    return (
        <>
            <Row gutter={16} data-attr="funnel-tab" className="funnel-tab">
                <Col xs={24} md={16} xl={isHorizontalUIEnabled ? undefined : 24}>
                    <div style={{ paddingRight: isSmallScreen ? undefined : 16 }}>
                        <div className="mb">
                            <ToggleButtonChartFilter />
                        </div>
                        <form
                            onSubmit={(e): void => {
                                e.preventDefault()
                                loadResults()
                            }}
                        >
                            <Row justify="space-between" align="middle">
                                <h4 className="secondary" style={{ marginBottom: 0 }}>
                                    Steps
                                </h4>
                                {clickhouseFeaturesEnabled && (
                                    <Row align="middle" style={{ padding: '0 4px' }}>
                                        {showGroupsOptions && (
                                            <span className="l5 text-muted-alt">
                                                <span style={{ marginRight: 5 }}>Aggregating by</span>
                                                <AggregationSelect
                                                    aggregationGroupTypeIndex={filters.aggregation_group_type_index}
                                                    onChange={(newValue) => {
                                                        setFilters({ aggregation_group_type_index: newValue })
                                                    }}
                                                />
                                            </span>
                                        )}
                                        <span className="l5 text-muted-alt" style={{ marginLeft: 8 }}>
                                            <span style={{ marginRight: 5 }}>Step Order</span>
                                            <FunnelStepOrderPicker />
                                            <Tooltip
                                                title={
                                                    <ul style={{ paddingLeft: '1.2rem' }}>
                                                        <li>
                                                            <b>Sequential</b> - Step B must happen after Step A, but any
                                                            number events can happen between A and B.
                                                        </li>
                                                        <li>
                                                            <b>Strict Order</b> - Step B must happen directly after Step
                                                            A without any events in between.
                                                        </li>
                                                        <li>
                                                            <b>Any Order</b> - Steps can be completed in any sequence.
                                                        </li>
                                                    </ul>
                                                }
                                            >
                                                <InfoCircleOutlined
                                                    className="info-indicator"
                                                    style={{ marginRight: 4 }}
                                                />
                                            </Tooltip>
                                        </span>
                                    </Row>
                                )}
                            </Row>
                            <ActionFilter
                                filters={filters}
                                setFilters={setFilters}
                                typeKey={`EditFunnel-action`}
                                hideMathSelector={true}
                                hideDeleteBtn={filterSteps.length === 1}
                                buttonCopy="Add funnel step"
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
                            />

                            {!clickhouseFeaturesEnabled && (
                                <>
                                    <hr />
                                    <Row style={{ justifyContent: 'flex-end' }}>
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
                            {clickhouseFeaturesEnabled && (
                                <>
                                    <hr />
                                    <h4 className="secondary">
                                        Exclusion Steps
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
                                    </h4>
                                    <FunnelExclusionsFilter />
                                </>
                            )}
                        </form>
                        <SaveModal
                            title="Save Funnel"
                            prompt="Enter the name of the funnel"
                            textLabel="Name"
                            visible={savingModal}
                            onCancel={closeModal}
                            onSubmit={onSubmit}
                        />
                    </div>
                </Col>
                <Col xs={24} md={8} xl={isHorizontalUIEnabled ? undefined : 24}>
                    {isSmallScreen && <hr />}
                    <GlobalFiltersTitle unit="steps" />
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
                    <TestAccountFilter filters={filters} onChange={setFilters} />
                    {clickhouseFeaturesEnabled && filters.funnel_viz_type === FunnelVizType.Steps && (
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
                                <BreakdownFilter
                                    filters={filters}
                                    setFilters={setFilters}
                                    useMultiBreakdown={
                                        featureFlags[FEATURE_FLAGS.BREAKDOWN_BY_MULTIPLE_PROPERTIES] !== undefined
                                    }
                                />
                            </Row>
                        </>
                    )}
                    <hr />
                    <h4 className="secondary">Options</h4>
                    <FunnelConversionWindowFilter />
                </Col>
            </Row>
        </>
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
