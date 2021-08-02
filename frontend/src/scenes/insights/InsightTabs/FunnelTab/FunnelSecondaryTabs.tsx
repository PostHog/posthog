import React from 'react'
import { Card, Row, Tooltip } from 'antd'
import { useActions, useValues } from 'kea'
import { GlobalFiltersTitle } from 'scenes/insights/common'
import { insightLogic } from 'scenes/insights/insightLogic'
import { SavedFunnels } from 'scenes/insights/SavedCard'
import { ViewType } from '~/types'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'

import { TestAccountFilter } from 'scenes/insights/TestAccountFilter'
import { InfoCircleOutlined } from '@ant-design/icons'
import { isValidPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { BreakdownFilter } from 'scenes/insights/BreakdownFilter'
import { CloseButton } from 'lib/components/CloseButton'
import { BreakdownType, FunnelVizType } from '~/types'
import { funnelLogic } from 'scenes/funnels/funnelLogic'

export function FunnelSecondaryTabs(): JSX.Element | null {
    const { activeView } = useValues(insightLogic)
    const { filters, clickhouseFeaturesEnabled } = useValues(funnelLogic)
    const { setFilters } = useActions(funnelLogic)
    if (activeView !== ViewType.FUNNELS) {
        return null
    }

    return (
        <>
            <Card>
                <GlobalFiltersTitle unit="steps" />
                <PropertyFilters
                    pageKey={`EditFunnel-property`}
                    propertyFilters={filters.properties || []}
                    onChange={(anyProperties) => {
                        setFilters({
                            properties: anyProperties.filter(isValidPropertyFilter),
                        })
                    }}
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
                        {filters.breakdown_type === 'cohort' && filters.breakdown ? (
                            <BreakdownFilter
                                filters={filters}
                                onChange={(breakdown: string, breakdown_type: BreakdownType): void =>
                                    setFilters({ breakdown, breakdown_type })
                                }
                                buttonExtraProps={{ type: 'link' }}
                            />
                        ) : (
                            <Row align="middle">
                                <BreakdownFilter
                                    filters={filters}
                                    onChange={(breakdown: string, breakdown_type: BreakdownType): void =>
                                        setFilters({ breakdown, breakdown_type })
                                    }
                                    buttonExtraProps={{ type: 'link' }}
                                />
                                {filters.breakdown && (
                                    <CloseButton
                                        onClick={(): void => setFilters({ breakdown: null, breakdown_type: null })}
                                        style={{ marginTop: 1, marginLeft: 5 }}
                                    />
                                )}
                            </Row>
                        )}
                    </>
                )}
            </Card>
            <Card title={<Row align="middle">Funnels Saved in Project</Row>} style={{ marginTop: 16 }}>
                <SavedFunnels />
            </Card>
        </>
    )
}
