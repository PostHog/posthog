import React from 'react'
import { useValues, useActions, useMountedLogic } from 'kea'
import clsx from 'clsx'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { ActionFilter } from '../../ActionFilter/ActionFilter'
import { Button, Col, Row, Tag } from 'antd'
import useBreakpoint from 'antd/lib/grid/hooks/useBreakpoint'
import { funnelCommandLogic } from './funnelCommandLogic'
import { InfoCircleOutlined } from '@ant-design/icons'
import { ToggleButtonChartFilter } from './ToggleButtonChartFilter'
import { Tooltip } from 'lib/components/Tooltip'
import {
    FunnelStepReference,
    FunnelVizType,
    StepOrderValue,
    PropertyGroupFilter,
    BreakdownAttributionType,
} from '~/types'
import { BreakdownFilter } from 'scenes/insights/BreakdownFilter'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { groupsModel } from '~/models/groupsModel'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { AggregationSelect } from 'scenes/insights/AggregationSelect'
import { IconArrowDropDown } from 'lib/components/icons'
import { FunnelConversionWindowFilter } from './FunnelConversionWindowFilter'
import { FunnelStepOrderPicker } from './FunnelStepOrderPicker'
import { FunnelExclusionsFilter } from './FunnelExclusionsFilter'
import { FunnelStepReferencePicker } from './FunnelStepReferencePicker'
import { convertPropertiesToPropertyGroup } from 'lib/utils'
import { PropertyGroupFilters } from 'lib/components/PropertyGroupFilters/PropertyGroupFilters'
import { MathAvailability } from 'scenes/insights/ActionFilter/ActionFilterRow/ActionFilterRow'
import { LemonSelect } from '@posthog/lemon-ui'

const FUNNEL_STEP_COUNT_LIMIT = 20

export function FunnelTab(): JSX.Element {
    const { insightProps, allEventNames } = useValues(insightLogic)
    const { loadResults } = useActions(insightLogic)
    const {
        isStepsEmpty,
        filters,
        aggregationTargetLabel,
        filterSteps,
        advancedOptionsUsedCount,
        breakdownAttributionStepOptions,
    } = useValues(funnelLogic(insightProps))
    const { setFilters, toggleAdvancedMode, setStepReference } = useActions(funnelLogic(insightProps))
    const { featureFlags } = useValues(featureFlagLogic)
    const { groupsTaxonomicTypes, showGroupsOptions } = useValues(groupsModel)
    const screens = useBreakpoint()
    useMountedLogic(funnelCommandLogic)

    const isSmallScreen = !screens.xl

    return (
        <Row gutter={16} data-attr="funnel-tab" className="funnel-tab">
            <Col xs={24} md={16} xl={24}>
                <div>
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
                            {
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
                            }
                        </Row>
                        <ActionFilter
                            bordered
                            filters={filters}
                            setFilters={setFilters}
                            typeKey={`EditFunnel-action`}
                            mathAvailability={MathAvailability.None}
                            hideDeleteBtn={filterSteps.length === 1}
                            buttonCopy="Add step"
                            showSeriesIndicator={!isStepsEmpty}
                            seriesIndicatorType="numeric"
                            entitiesLimit={FUNNEL_STEP_COUNT_LIMIT}
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
            <Col xs={24} md={8} xl={24}>
                <hr />
                <div className="mt" />
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
                    pageKey="EditFunnel-property"
                    eventNames={allEventNames}
                    filters={filters}
                    setTestFilters={(testFilters) => setFilters(testFilters)}
                />

                {filters.funnel_viz_type === FunnelVizType.Steps && (
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
                                buttonType="default"
                                useMultiBreakdown={!!featureFlags[FEATURE_FLAGS.BREAKDOWN_BY_MULTIPLE_PROPERTIES]}
                            />
                        </Row>
                        {featureFlags[FEATURE_FLAGS.BREAKDOWN_ATTRIBUTION] && (
                            <>
                                <h4 className="secondary mt">
                                    Attribution Type
                                    <Tooltip placement="right" title="filler">
                                        <InfoCircleOutlined className="info-indicator" />
                                    </Tooltip>
                                </h4>
                                <Row>
                                    <LemonSelect
                                        placeholder="Attribution"
                                        options={{
                                            [BreakdownAttributionType.FirstTouch]: { label: 'First touchpoint' },
                                            [BreakdownAttributionType.LastTouch]: { label: 'Last touchpoint' },
                                            [BreakdownAttributionType.AllSteps]: { label: 'All Steps' },
                                            ...(filters.funnel_order_type === StepOrderValue.UNORDERED
                                                ? { [BreakdownAttributionType.Step]: { label: 'Any step' } }
                                                : {
                                                      [BreakdownAttributionType.Step]: {
                                                          label: 'Specific step',
                                                          element: (
                                                              <LemonSelect
                                                                  outlined
                                                                  className="ml-05"
                                                                  onChange={(value) => {
                                                                      if (value) {
                                                                          setFilters({
                                                                              breakdown_attribution_type:
                                                                                  BreakdownAttributionType.Step,
                                                                              breakdown_attribution_value: value,
                                                                          })
                                                                      }
                                                                  }}
                                                                  placeholder={`Step ${
                                                                      filters.breakdown_attribution_value || 1
                                                                  }`}
                                                                  options={breakdownAttributionStepOptions}
                                                              />
                                                          ),
                                                      },
                                                  }),
                                        }}
                                        onChange={(value) => {
                                            if (value) {
                                                setFilters({
                                                    breakdown_attribution_type: value,
                                                    breakdown_attribution_value: 0,
                                                })
                                            }
                                        }}
                                        dropdownMaxContentWidth={true}
                                        outlined
                                        data-attr="breakdown-attributions"
                                    />
                                </Row>
                            </>
                        )}
                    </>
                )}

                {
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
                                                Exclude {aggregationTargetLabel.plural}{' '}
                                                {filters.aggregation_group_type_index != undefined ? 'that' : 'who'}{' '}
                                                completed the specified event between two specific steps. Note that
                                                these {aggregationTargetLabel.plural} will be{' '}
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
                }
            </Col>
        </Row>
    )
}
