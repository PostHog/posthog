import React from 'react'
import { Button, Table } from 'antd'
import Column from 'antd/lib/table/Column'
import { useActions, useValues } from 'kea'
import { RiseOutlined, FallOutlined } from '@ant-design/icons'
import { IconSelectEvents, IconUnfoldLess, IconUnfoldMore } from 'lib/components/icons'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import {
    EntityTypes,
    FunnelCorrelation,
    FunnelCorrelationResultsType,
    FunnelCorrelationType,
    PropertyFilter,
    PropertyOperator,
} from '~/types'
import Checkbox from 'antd/lib/checkbox/Checkbox'
import { insightLogic } from 'scenes/insights/insightLogic'
import { ValueInspectorButton } from 'scenes/funnels/FunnelBarGraph'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import './FunnelCorrelationTable.scss'
import { Tooltip } from 'lib/components/Tooltip'
import { elementsToAction } from 'scenes/events/createActionFromEvent'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

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
        correlationsLoading,
        eventWithPropertyCorrelationsLoading,
        nestedTableExpandedKeys,
    } = useValues(logic)
    const {
        setCorrelationTypes,
        loadEventWithPropertyCorrelations,
        openCorrelationPersonsModal,
        addNestedTableExpandedKey,
        removeNestedTableExpandedKey,
    } = useActions(logic)

    const { reportCorrelationInteraction } = useActions(eventUsageLogic)

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

    const parseEventAndProperty = (
        event: FunnelCorrelation['event']
    ): { name: string; properties?: PropertyFilter[] } => {
        const components = event.event.split('::')
        /*
          The `event` is either an event name, or event::property::property_value
        */
        if (components.length === 1) {
            return { name: components[0] }
        } else if (components[0] === '$autocapture') {
            // We use elementsToAction to generate the required property filters
            const elementData = elementsToAction(event.elements)
            return {
                name: components[0],
                properties: Object.entries(elementData)
                    .filter(([, propertyValue]) => !!propertyValue)
                    .map(([propertyKey, propertyValue]) => ({
                        key: propertyKey,
                        operator: PropertyOperator.Exact,
                        type: 'element',
                        value: [propertyValue as string],
                    })),
            }
        } else {
            return {
                name: components[0],
                properties: [
                    { key: components[1], operator: PropertyOperator.Exact, value: components[2], type: 'event' },
                ],
            }
        }
    }
    const renderSuccessCount = (record: FunnelCorrelation): JSX.Element => {
        const { name, properties } = parseEventAndProperty(record.event)

        return (
            <ValueInspectorButton
                onClick={() => {
                    openCorrelationPersonsModal(
                        { id: name, type: EntityTypes.EVENTS, properties },
                        true,
                        record.result_type
                    )
                }}
            >
                {record.success_count}
            </ValueInspectorButton>
        )
    }

    const renderFailureCount = (record: FunnelCorrelation): JSX.Element => {
        const { name, properties } = parseEventAndProperty(record.event)

        return (
            <ValueInspectorButton
                onClick={() => {
                    openCorrelationPersonsModal(
                        { id: name, type: EntityTypes.EVENTS, properties },
                        false,
                        record.result_type
                    )
                }}
            >
                {record.failure_count}
            </ValueInspectorButton>
        )
    }

    const renderNestedTable = (eventName: string): JSX.Element => {
        return (
            <>
                <Table
                    dataSource={eventWithPropertyCorrelationsValues[eventName]}
                    loading={eventWithPropertyCorrelationsLoading}
                    rowKey={(record: FunnelCorrelation) => record.event.event}
                    style={{ margin: '1rem' }}
                    scroll={{ x: 'max-content' }}
                    pagination={{
                        pageSize: 5,
                        hideOnSinglePage: true,
                        onChange: (page, page_size) =>
                            reportCorrelationInteraction(
                                FunnelCorrelationResultsType.EventWithProperties,
                                'pagination change',
                                { page, page_size }
                            ),
                    }}
                >
                    <Column
                        title="Correlated Properties"
                        key="eventName"
                        render={(_, record: FunnelCorrelation) => renderOddsRatioTextRecord(record)}
                        align="left"
                        width="80%"
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
                        title="Actions"
                        key="actions"
                        render={(_, record: FunnelCorrelation) => <CorrelationActionsCell record={record} />}
                        align="center"
                    />
                </Table>
            </>
        )
    }

    return stepsWithCount.length > 1 ? (
        <div className="funnel-correlation-table">
            <span className="funnel-correlation-header">
                <span className="table-header">
                    <IconSelectEvents style={{ marginRight: 4 }} />
                    CORRELATED EVENTS
                </span>
                <span className="table-options">
                    <p className="title">CORRELATION</p>
                    <div
                        className="tab-btn ant-btn"
                        style={{ marginRight: '2px', paddingTop: '1px', paddingBottom: '1px' }}
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
                    </div>
                    <div
                        className="tab-btn ant-btn"
                        style={{ marginRight: '5px', paddingTop: '1px', paddingBottom: '1px' }}
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
                    </div>
                </span>
            </span>
            <Table
                dataSource={correlationValues}
                loading={correlationsLoading}
                size="small"
                scroll={{ x: 'max-content' }}
                rowKey={(record: FunnelCorrelation) => record.event.event}
                pagination={{
                    pageSize: 5,
                    hideOnSinglePage: true,
                    onChange: () => reportCorrelationInteraction(FunnelCorrelationResultsType.Events, 'load more'),
                }}
                style={{ marginTop: '1rem' }}
                expandable={{
                    expandedRowRender: (record) => renderNestedTable(record.event.event),
                    expandedRowKeys: nestedTableExpandedKeys,
                    rowExpandable: () => true,
                    /* eslint-disable react/display-name */
                    expandIcon: ({ expanded, onExpand, record }) =>
                        expanded ? (
                            <Tooltip title="Collapse">
                                <div
                                    style={{ cursor: 'pointer', opacity: 0.5, fontSize: 24 }}
                                    onClick={(e) => {
                                        removeNestedTableExpandedKey(record.event.event)
                                        onExpand(record, e)
                                    }}
                                >
                                    <IconUnfoldLess />
                                </div>
                            </Tooltip>
                        ) : (
                            <Tooltip title="Expand to see correlated properties for this event">
                                <div
                                    style={{ cursor: 'pointer', opacity: 0.5, fontSize: 24 }}
                                    onClick={(e) => {
                                        !eventHasPropertyCorrelations(record.event.event) &&
                                            loadEventWithPropertyCorrelations(record.event.event)
                                        addNestedTableExpandedKey(record.event.event)
                                        onExpand(record, e)
                                    }}
                                >
                                    <IconUnfoldMore />
                                </div>
                            </Tooltip>
                        ),
                    /* eslint-enable react/display-name */
                }}
            >
                <Column
                    title="Event"
                    key="eventName"
                    render={(_, record: FunnelCorrelation) => renderOddsRatioTextRecord(record)}
                    align="left"
                    width="60%"
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
                    title="Actions"
                    key="operation"
                    render={(_, record: FunnelCorrelation) => <CorrelationActionsCell record={record} />}
                />
            </Table>
        </div>
    ) : null
}

const CorrelationActionsCell = ({ record }: { record: FunnelCorrelation }): JSX.Element => {
    const { insightProps } = useValues(insightLogic)
    const logic = funnelLogic(insightProps)
    const { excludeEventPropertyFromProject, excludeEventFromProject } = useActions(logic)
    const { isEventPropertyExcluded, isEventExcluded } = useValues(logic)
    const components = record.event.event.split('::')

    return (
        <Button
            disabled={
                record.result_type === FunnelCorrelationResultsType.EventWithProperties
                    ? isEventPropertyExcluded(components[1])
                    : isEventExcluded(components[0])
            }
            onClick={() =>
                record.result_type === FunnelCorrelationResultsType.EventWithProperties
                    ? excludeEventPropertyFromProject(components[0], components[1])
                    : excludeEventFromProject(components[0])
            }
            type="link"
        >
            Exclude
        </Button>
    )
}
