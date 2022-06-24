import React from 'react'
import { useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { BreakdownAttributionType, EditorFilterProps, InsightType, StepOrderValue } from '~/types'
import { BreakdownFilter } from 'scenes/insights/BreakdownFilter'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { InfoCircleOutlined } from '@ant-design/icons'
import { LemonSelect } from '@posthog/lemon-ui'
import { Tooltip, Row } from 'antd'
import { funnelLogic } from 'scenes/funnels/funnelLogic'

export function EFTrendsBreakdown({ filters, insightProps }: EditorFilterProps): JSX.Element {
    const { setFilters } = useActions(trendsLogic(insightProps))

    const { featureFlags } = useValues(featureFlagLogic)
    const { breakdownAttributionStepOptions } = useValues(funnelLogic(insightProps))

    const useMultiBreakdown =
        filters.insight !== InsightType.TRENDS && !!featureFlags[FEATURE_FLAGS.BREAKDOWN_BY_MULTIPLE_PROPERTIES]
    const isFunnels = filters.insight === InsightType.FUNNELS

    return (
        <>
            <BreakdownFilter
                filters={filters}
                setFilters={setFilters}
                buttonType="default"
                useMultiBreakdown={useMultiBreakdown}
            />
            {isFunnels && featureFlags[FEATURE_FLAGS.BREAKDOWN_ATTRIBUTION] && (
                <>
                    <h4 className="mt">
                        Attribution Type
                        <Tooltip placement="right" title="filler">
                            <InfoCircleOutlined className="info-indicator" />
                        </Tooltip>
                    </h4>
                    <Row>
                        <LemonSelect
                            value={filters.breakdown_attribution_type || BreakdownAttributionType.FirstTouch}
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
                                                                  breakdown_attribution_value: parseInt(value),
                                                              })
                                                          }
                                                      }}
                                                      placeholder={`Step ${
                                                          filters.breakdown_attribution_value
                                                              ? filters.breakdown_attribution_value + 1
                                                              : 1
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
                                        breakdown_attribution_value: filters.breakdown_attribution_value || 0,
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
    )
}
