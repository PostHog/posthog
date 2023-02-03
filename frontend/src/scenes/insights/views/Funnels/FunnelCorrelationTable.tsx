import { useEffect, useState } from 'react'
import { Row, Table } from 'antd'
import Column from 'antd/lib/table/Column'
import { useActions, useValues } from 'kea'
import { RiseOutlined, FallOutlined, EllipsisOutlined, InfoCircleOutlined } from '@ant-design/icons'
import { IconSelectEvents, IconUnfoldLess, IconUnfoldMore } from 'lib/lemon-ui/icons'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { FunnelCorrelation, FunnelCorrelationResultsType, FunnelCorrelationType } from '~/types'
import Checkbox from 'antd/lib/checkbox/Checkbox'
import { insightLogic } from 'scenes/insights/insightLogic'
import { ValueInspectorButton } from 'scenes/funnels/ValueInspectorButton'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import './FunnelCorrelationTable.scss'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { VisibilitySensor } from 'lib/components/VisibilitySensor/VisibilitySensor'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { CorrelationMatrix } from './CorrelationMatrix'
import { capitalizeFirstLetter } from 'lib/utils'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'

export function FunnelCorrelationTable(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const logic = funnelLogic(insightProps)
    const {
        steps,
        correlationValues,
        correlationTypes,
        eventHasPropertyCorrelations,
        eventWithPropertyCorrelationsValues,
        parseDisplayNameForCorrelation,
        correlationsLoading,
        eventWithPropertyCorrelationsLoading,
        nestedTableExpandedKeys,
        correlationPropKey,
        filters,
        aggregationTargetLabel,
    } = useValues(logic)
    const {
        setCorrelationTypes,
        loadEventWithPropertyCorrelations,
        addNestedTableExpandedKey,
        removeNestedTableExpandedKey,
        openCorrelationPersonsModal,
        loadCorrelations,
    } = useActions(logic)

    const { reportCorrelationInteraction } = useActions(eventUsageLogic)

    // Load correlations only if this component is mounted, and then reload if filters change
    useEffect(() => {
        loadCorrelations({})
    }, [filters])

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
                    {is_success ? <RiseOutlined className="text-success" /> : <FallOutlined className="text-danger" />}{' '}
                    <PropertyKeyInfo value={first_value} />
                    {second_value !== undefined && (
                        <>
                            {' :: '}
                            <PropertyKeyInfo value={second_value} disablePopover />
                        </>
                    )}
                </h4>
                <div>
                    {capitalizeFirstLetter(aggregationTargetLabel.plural)}{' '}
                    {filters.aggregation_group_type_index != undefined ? 'that' : 'who'} converted were{' '}
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
                <div className="flex flex-col items-center py-2">
                    <Spinner className="text-2xl mb-2" />
                    <h3 className="mb-1 text-md font-semibold">Loading correlation results…</h3>
                    <p className="m-0 text-xs text-muted">This process can take up to 20 seconds.</p>
                </div>
            )
        }

        return (
            <div>
                <h4 className="pl-4">Correlated properties</h4>
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

    return steps.length > 1 ? (
        <VisibilitySensor id={correlationPropKey} offset={152}>
            <div className="funnel-correlation-table">
                <span className="funnel-correlation-header">
                    <span className="table-header">
                        <IconSelectEvents className="mr-1 text-2xl opacity-50" />
                        CORRELATED EVENTS
                    </span>
                    <span className="table-options">
                        <p className="title">CORRELATION</p>
                        <div
                            className="tab-btn ant-btn"
                            onClick={() => onClickCorrelationType(FunnelCorrelationType.Success)}
                        >
                            <Checkbox
                                checked={correlationTypes.includes(FunnelCorrelationType.Success)}
                                className="pointer-events-none"
                            >
                                Success
                            </Checkbox>
                        </div>
                        <div
                            className="tab-btn ant-btn"
                            onClick={() => onClickCorrelationType(FunnelCorrelationType.Failure)}
                        >
                            <Checkbox
                                checked={correlationTypes.includes(FunnelCorrelationType.Failure)}
                                className="pointer-events-none"
                            >
                                Drop-off
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
                        rowExpandable: () => filters.aggregation_group_type_index === undefined,
                        /* eslint-disable react/display-name */
                        expandIcon: ({ expanded, onExpand, record, expandable }) => {
                            if (!expandable) {
                                return null
                            }
                            return expanded ? (
                                <Tooltip title="Collapse">
                                    <LemonButton
                                        icon={<IconUnfoldLess />}
                                        status="stealth"
                                        type="tertiary"
                                        active
                                        noPadding
                                        onClick={(e) => {
                                            removeNestedTableExpandedKey(record.event.event)
                                            onExpand(record, e)
                                        }}
                                    />
                                </Tooltip>
                            ) : (
                                <Tooltip title="Expand to see correlated properties for this event">
                                    <LemonButton
                                        icon={<IconUnfoldMore />}
                                        status="stealth"
                                        type="tertiary"
                                        noPadding
                                        onClick={(e) => {
                                            !eventHasPropertyCorrelations(record.event.event) &&
                                                loadEventWithPropertyCorrelations(record.event.event)
                                            addNestedTableExpandedKey(record.event.event)
                                            onExpand(record, e)
                                        }}
                                    />
                                </Tooltip>
                            )
                        },
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
                            <div className="flex items-center">
                                Completed
                                <Tooltip
                                    title={`${capitalizeFirstLetter(aggregationTargetLabel.plural)} ${
                                        filters.aggregation_group_type_index != undefined ? 'that' : 'who'
                                    } performed the event and completed the entire funnel.`}
                                >
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
                            <div className="flex items-center">
                                Dropped off
                                <Tooltip
                                    title={
                                        <>
                                            {capitalizeFirstLetter(aggregationTargetLabel.plural)}{' '}
                                            {filters.aggregation_group_type_index != undefined ? 'that' : 'who'}{' '}
                                            performed the event and did <b>not complete</b> the entire funnel.
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
            <Popover
                visible={popoverOpen}
                actionable
                onClickOutside={() => setPopoverOpen(false)}
                overlay={
                    <>
                        {record.result_type === FunnelCorrelationResultsType.Events && (
                            <LemonButton onClick={() => setFunnelCorrelationDetails(record)} fullWidth status="stealth">
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
                            status="stealth"
                        >
                            Exclude event from project
                        </LemonButton>
                    </>
                }
            >
                <LemonButton status="stealth" onClick={() => setPopoverOpen(!popoverOpen)}>
                    <EllipsisOutlined className="insight-dropdown-actions" />
                </LemonButton>
            </Popover>
        </Row>
    )
}
