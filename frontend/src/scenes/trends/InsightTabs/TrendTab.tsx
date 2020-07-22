import React from 'react'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { ActionFilter } from '../ActionFilter/ActionFilter'
import { Tooltip, Row } from 'antd'
import { BreakdownFilter } from '../BreakdownFilter'
import { CloseButton } from 'lib/utils'
import { ShownAsFilter } from '../ShownAsFilter'
import { InfoCircleOutlined } from '@ant-design/icons'

interface Props {
    filters: Record<string, unknown>
    onEntityChanged: (payload: Record<string, unknown>) => void
    onBreakdownChanged: (breakdownPayload: BreakdownPayload) => void
    onShownAsChanged: (shown_as: string) => void
}

interface BreakdownPayload {
    breakdown: boolean
    breakdown_type: string
}

export function TrendTab(props: Props): JSX.Element {
    const { filters, onEntityChanged, onBreakdownChanged, onShownAsChanged } = props

    return (
        <>
            <ActionFilter
                filters={filters}
                setFilters={(payload): void => onEntityChanged(payload)}
                typeKey="trends"
                hideMathSelector={false}
            />
            <hr />
            <h4 className="secondary">Filters</h4>
            <PropertyFilters pageKey="trends-filters" />
            <hr />
            <h4 className="secondary">
                Break down by
                <Tooltip
                    placement="right"
                    title="Use breakdown to see the volume of events for each variation of that property. For example, breaking down by $current_url will give you the event volume for each url your users have visited."
                >
                    <InfoCircleOutlined className="info" style={{ color: '#007bff' }}></InfoCircleOutlined>
                </Tooltip>
            </h4>
            <Row>
                <BreakdownFilter
                    filters={filters}
                    onChange={(breakdown, breakdown_type): void => onBreakdownChanged({ breakdown, breakdown_type })}
                />
                {filters.breakdown && (
                    <CloseButton
                        onClick={(): void => onBreakdownChanged({ breakdown: false, breakdown_type: null })}
                        style={{ marginTop: 1, marginLeft: 10 }}
                    />
                )}
            </Row>
            <hr />
            <h4 className="secondary">
                Shown as
                <Tooltip
                    placement="right"
                    title='
                                            Stickiness shows you how many days users performed an action within the timeframe. If a user
                                            performed an action on Monday and again on Friday, it would be shown 
                                            as "2 days".'
                >
                    <InfoCircleOutlined className="info" style={{ color: '#007bff' }}></InfoCircleOutlined>
                </Tooltip>
            </h4>
            <ShownAsFilter filters={filters} onChange={(shown_as): void => onShownAsChanged(shown_as)} />
        </>
    )
}
