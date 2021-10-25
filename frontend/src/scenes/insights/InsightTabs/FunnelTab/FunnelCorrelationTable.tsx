import React from 'react'
import { Col, Row, Table } from 'antd'
import Column from 'antd/lib/table/Column'
import { useActions, useValues } from 'kea'
import { RiseOutlined, FallOutlined } from '@ant-design/icons'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { EntityTypes, FunnelCorrelation, FunnelCorrelationType, PropertyFilter, PropertyOperator } from '~/types'
import Checkbox from 'antd/lib/checkbox/Checkbox'
import { insightLogic } from 'scenes/insights/insightLogic'
import { ValueInspectorButton } from 'scenes/funnels/FunnelBarGraph'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'

export function FunnelCorrelationTable(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const logic = funnelLogic(insightProps)
    const {
        stepsWithCount,
        correlationValues,
        correlationTypes,
        eventHasPropertyCorrelations,
        eventWithPropertyCorrelationsValues,
        parseDisplayNameForCorrelation,
    } = useValues(logic)
    const { setCorrelationTypes, loadEventWithPropertyCorrelations, openCorrelationPersonsModal } = useActions(logic)

    const onClickCorrelationType = (correlationType: FunnelCorrelationType): void => {
        if (correlationTypes) {
            if (correlationTypes.includes(correlationType)) {
                setCorrelationTypes(correlationTypes.filter((types) => types !== correlationType))
            } else {
                setCorrelationTypes([...correlationTypes, correlationType])
            }
        } else {
            setCorrelationTypes([correlationType])
        }
    }

    const renderOddsRatioTextRecord = (record: FunnelCorrelation): JSX.Element => {
        const get_friendly_numeric_value = (value: number): string => {
            if (value < 10 && !Number.isInteger(value)) {
                return value.toFixed(1)
            }

            return value.toFixed()
        }
        const is_success = record.correlation_type === FunnelCorrelationType.Success

        const { first_value, second_value } = parseDisplayNameForCorrelation(record)

        return (
            <>
                <h4>
                    {is_success ? (
                        <RiseOutlined style={{ color: 'green' }} />
                    ) : (
                        <FallOutlined style={{ color: 'red' }} />
                    )}{' '}
                    <PropertyKeyInfo value={first_value} />
                    {second_value !== undefined && (
                        <>
                            {' :: '}
                            <PropertyKeyInfo value={second_value} disablePopover />
                        </>
                    )}
                </h4>
                <div>
                    People who converted were{' '}
                    <mark>
                        <b>
                            {get_friendly_numeric_value(record.odds_ratio)}x {is_success ? 'more' : 'less'} likely
                        </b>
                    </mark>{' '}
                    to do this event
                </div>
            </>
        )
    }

    const parseEventAndProperty = (item: string): { name: string; property?: PropertyFilter } => {
        const components = item.split('::')
        if (components.length === 1) {
            return { name: components[0] }
        } else {
            return {
                name: components[0],
                property: { key: components[1], operator: PropertyOperator.Exact, value: components[2], type: 'event' },
            }
        }
    }
    const renderSuccessCount = (record: FunnelCorrelation): JSX.Element => {
        const { name, property } = parseEventAndProperty(record.event?.event || '')

        return (
            <ValueInspectorButton
                onClick={() => {
                    openCorrelationPersonsModal(
                        { id: name, type: EntityTypes.EVENTS, properties: property ? [property] : [] },
                        true
                    )
                }}
            >
                {record.success_count}
            </ValueInspectorButton>
        )
    }

    const renderFailureCount = (record: FunnelCorrelation): JSX.Element => {
        const { name, property } = parseEventAndProperty(record.event?.event || '')

        return (
            <ValueInspectorButton
                onClick={() => {
                    openCorrelationPersonsModal(
                        { id: name, type: EntityTypes.EVENTS, properties: property ? [property] : [] },
                        false
                    )
                }}
            >
                {record.failure_count}
            </ValueInspectorButton>
        )
    }

    const renderNestedTable = (eventName?: string): JSX.Element => {
        if (!eventName) {
            return <p>Unable to find property correlations for event.</p>
        }

        return (
            <Table
                dataSource={eventWithPropertyCorrelationsValues[eventName]}
                rowKey="rowKey"
                style={{ marginTop: '1rem' }}
            >
                <Column
                    title="Correlated Events"
                    key="eventName"
                    render={(_, record: FunnelCorrelation) => renderOddsRatioTextRecord(record)}
                    align="left"
                />
                <Column
                    title="Completed"
                    key="success_count"
                    render={(_, record: FunnelCorrelation) => renderSuccessCount(record)}
                    width={90}
                    align="center"
                />
                <Column
                    title="Dropped off"
                    key="failure_count"
                    render={(_, record: FunnelCorrelation) => renderFailureCount(record)}
                    width={100}
                    align="center"
                />
            </Table>
        )
    }

    return stepsWithCount.length > 1 ? (
        <Table
            dataSource={correlationValues}
            scroll={{ x: 'max-content' }}
            size="small"
            rowKey={(record: FunnelCorrelation) => record.event?.event || 'rowKey'}
            pagination={{ pageSize: 100, hideOnSinglePage: true }}
            style={{ marginTop: '1rem' }}
            expandable={{
                expandedRowRender: (record) => renderNestedTable(record.event?.event),
                rowExpandable: (record) => !!record.event?.event && eventHasPropertyCorrelations(record.event?.event),
            }}
            title={() => (
                <>
                    <Row align="middle">
                        <Col xs={20} sm={20} xl={6}>
                            <b>Correlation Analysis for:</b>
                        </Col>
                        <Col
                            xs={20}
                            sm={20}
                            xl={4}
                            className="tab-btn left ant-btn"
                            onClick={() => onClickCorrelationType(FunnelCorrelationType.Success)}
                        >
                            <Checkbox
                                checked={correlationTypes.includes(FunnelCorrelationType.Success)}
                                style={{
                                    pointerEvents: 'none',
                                }}
                            >
                                Success
                            </Checkbox>
                        </Col>
                        <Col
                            xs={20}
                            sm={20}
                            xl={4}
                            className="tab-btn left ant-btn"
                            onClick={() => onClickCorrelationType(FunnelCorrelationType.Failure)}
                        >
                            <Checkbox
                                checked={correlationTypes.includes(FunnelCorrelationType.Failure)}
                                style={{
                                    pointerEvents: 'none',
                                }}
                            >
                                Dropoff
                            </Checkbox>
                        </Col>
                    </Row>
                </>
            )}
        >
            <Column
                title="Correlated Events"
                key="eventName"
                render={(_, record: FunnelCorrelation) => renderOddsRatioTextRecord(record)}
                align="left"
                ellipsis
            />
            <Column
                title="Completed"
                key="success_count"
                render={(_, record: FunnelCorrelation) => renderSuccessCount(record)}
                width={90}
                align="center"
            />
            <Column
                title="Dropped off"
                key="failure_count"
                render={(_, record: FunnelCorrelation) => renderFailureCount(record)}
                width={100}
                align="center"
            />
            <Column
                title="Property correlations"
                key="operation"
                render={(_, record: FunnelCorrelation) => (
                    <a onClick={() => record.event?.event && loadEventWithPropertyCorrelations(record.event?.event)}>
                        Run
                    </a>
                )}
            />
        </Table>
    ) : null
}
