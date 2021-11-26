import React, { useState } from 'react'
import { Row, Spin, Table } from 'antd'
import Column from 'antd/lib/table/Column'
import { useActions, useValues } from 'kea'
import { RiseOutlined, FallOutlined, EllipsisOutlined, InfoCircleOutlined } from '@ant-design/icons'
import { IconSelectEvents, IconUnfoldLess, IconUnfoldMore } from 'lib/components/icons'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { FunnelCorrelation, FunnelCorrelationResultsType, FunnelCorrelationType } from '~/types'
import Checkbox from 'antd/lib/checkbox/Checkbox'
import { insightLogic } from 'scenes/insights/insightLogic'
import { ValueInspectorButton } from 'scenes/funnels/FunnelBarGraph'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import './FunnelCorrelationTable.scss'
import { Tooltip } from 'lib/components/Tooltip'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { VisibilitySensor } from 'lib/components/VisibilitySensor/VisibilitySensor'
import { LemonButton } from 'lib/components/LemonButton'
import { Popup } from 'lib/components/Popup/Popup'
import { CorrelationMatrix } from './CorrelationMatrix'

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
        correlationPropKey,
    } = useValues(logic)

    const {
        setCorrelationTypes,
        loadEventWithPropertyCorrelations,
        addNestedTableExpandedKey,
        removeNestedTableExpandedKey,
        openCorrelationPersonsModal,
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
                    to{' '}
                    {record.result_type === FunnelCorrelationResultsType.EventWithProperties
                        ? 'have this event property'
                        : 'do this event'}
                </div>
                <CorrelationMatrix />
            </>
        )
    }

    const renderSuccessCount = (record: FunnelCorrelation): JSX.Element => {
        return (
            <ValueInspectorButton
                onClick={() => {
                    openCorrelationPersonsModal(record, true)
                }}
            >
                {record.success_count}
            </ValueInspectorButton>
        )
    }

    const renderFailureCount = (record: FunnelCorrelation): JSX.Element => {
        return (
            <ValueInspectorButton
                onClick={() => {
                    openCorrelationPersonsModal(record, false)
                }}
            >
                {record.failure_count}
            </ValueInspectorButton>
        )
    }

    const renderNestedTable = (eventName: string): JSX.Element => {
        if (eventWithPropertyCorrelationsLoading) {
            return (
                <div className="nested-properties-loading">
                    <Spin />
                    <h3>Loading correlation results</h3>
                    <p>This process can take up to 20 seconds. </p>
                </div>
            )
        }

        return (
            <div>
                <h4 style={{ paddingLeft: 16 }}>Correlated properties</h4>
                <Table
                    dataSource={eventWithPropertyCorrelationsValues[eventName]}
                    rowKey={(record: FunnelCorrelation) => record.event.event}
                    className="nested-properties-table"
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
                        title="Property"
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
                        width={120}
                        align="center"
                    />

                    <Column
                        title=""
                        key="actions"
                        render={(_, record: FunnelCorrelation) => <CorrelationActionsCell record={record} />}
                        align="center"
                        width={30}
                    />
                </Table>
            </div>
        )
    }

    return stepsWithCount.length > 1 ? (
        <VisibilitySensor id={correlationPropKey} offset={152}>
            <div className="funnel-correlation-table">
                <span className="funnel-correlation-header">
                    <span className="table-header">
                        <IconSelectEvents style={{ marginRight: 4, fontSize: 24, opacity: 0.5 }} />
                        CORRELATED EVENTS
                    </span>
                    <span className="table-options">
                        <p className="title">CORRELATION</p>
                        <div
                            className="tab-btn ant-btn"
                            style={{
                                paddingTop: '1px',
                                paddingBottom: '1px',
                                borderTopRightRadius: 0,
                                borderBottomRightRadius: 0,
                            }}
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
                            style={{
                                marginRight: '8px',
                                paddingTop: '1px',
                                paddingBottom: '1px',
                                borderTopLeftRadius: 0,
                                borderBottomLeftRadius: 0,
                            }}
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
                        ellipsis
                    />
                    <Column
                        title={
                            <div className="flex-center">
                                Completed
                                <Tooltip title="Users who performed the event and completed the entire funnel.">
                                    <InfoCircleOutlined className="column-info" />
                                </Tooltip>
                            </div>
                        }
                        key="success_count"
                        render={(_, record: FunnelCorrelation) => renderSuccessCount(record)}
                        width={90}
                        align="center"
                    />
                    <Column
                        title={
                            <div className="flex-center">
                                Dropped off
                                <Tooltip
                                    title={
                                        <>
                                            Users who performed the event and did <b>not complete</b> the entire funnel.
                                        </>
                                    }
                                >
                                    <InfoCircleOutlined className="column-info" />
                                </Tooltip>
                            </div>
                        }
                        key="failure_count"
                        render={(_, record: FunnelCorrelation) => renderFailureCount(record)}
                        width={120}
                        align="center"
                    />
                    <Column
                        title=""
                        key="actions"
                        render={(_, record: FunnelCorrelation) => <CorrelationActionsCell record={record} />}
                        width={30}
                    />
                </Table>
            </div>
        </VisibilitySensor>
    ) : null
}

const CorrelationActionsCell = ({ record }: { record: FunnelCorrelation }): JSX.Element => {
    const { insightProps } = useValues(insightLogic)
    const logic = funnelLogic(insightProps)
    const { excludeEventPropertyFromProject, excludeEventFromProject, setFunnelCorrelationDetails } = useActions(logic)
    const { isEventPropertyExcluded, isEventExcluded } = useValues(logic)
    const components = record.event.event.split('::')
    const [popoverOpen, setPopoverOpen] = useState(false)

    return (
        <Row style={{ justifyContent: 'flex-end' }}>
            <Popup
                visible={popoverOpen}
                actionable
                onClickOutside={() => setPopoverOpen(false)}
                overlay={
                    <>
                        {record.result_type === FunnelCorrelationResultsType.Events && (
                            <LemonButton onClick={() => setFunnelCorrelationDetails(record)} fullWidth type="stealth">
                                View correlation details
                            </LemonButton>
                        )}
                        <LemonButton
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
                            fullWidth
                            title="Remove this event from any correlation analysis report in this project."
                            type="stealth"
                        >
                            Exclude event from project
                        </LemonButton>
                    </>
                }
            >
                <LemonButton type="stealth" onClick={() => setPopoverOpen(!popoverOpen)}>
                    <EllipsisOutlined
                        style={{ color: 'var(--primary)', fontSize: 24 }}
                        className="insight-dropdown-actions"
                    />
                </LemonButton>
            </Popup>
        </Row>
    )
}
