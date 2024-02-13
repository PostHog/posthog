import './FunnelCorrelationTable.scss'

import { IconInfo } from '@posthog/icons'
import { LemonCheckbox } from '@posthog/lemon-ui'
import { ConfigProvider, Empty, Table } from 'antd'
import Column from 'antd/lib/table/Column'
import { useActions, useValues } from 'kea'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { VisibilitySensor } from 'lib/components/VisibilitySensor/VisibilitySensor'
import { IconSelectEvents, IconTrendingDown, IconTrendUp, IconUnfoldLess, IconUnfoldMore } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { capitalizeFirstLetter } from 'lib/utils'
import { useEffect } from 'react'
import { funnelCorrelationLogic } from 'scenes/funnels/funnelCorrelationLogic'
import { funnelCorrelationUsageLogic } from 'scenes/funnels/funnelCorrelationUsageLogic'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { funnelPersonsModalLogic } from 'scenes/funnels/funnelPersonsModalLogic'
import { parseDisplayNameForCorrelation } from 'scenes/funnels/funnelUtils'
import { ValueInspectorButton } from 'scenes/funnels/ValueInspectorButton'
import { insightLogic } from 'scenes/insights/insightLogic'

import { FunnelCorrelation, FunnelCorrelationResultsType, FunnelCorrelationType } from '~/types'

import { EventCorrelationActionsCell } from './CorrelationActionsCell'
import { CorrelationMatrix } from './CorrelationMatrix'

export function FunnelCorrelationTable(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { steps, querySource, aggregationTargetLabel } = useValues(funnelDataLogic(insightProps))
    const {
        correlationTypes,
        correlationsLoading,
        correlationValues,
        loadedEventCorrelationsTableOnce,
        eventHasPropertyCorrelations,
        eventWithPropertyCorrelationsLoading,
        eventWithPropertyCorrelationsValues,
        nestedTableExpandedKeys,
    } = useValues(funnelCorrelationLogic(insightProps))
    const {
        setCorrelationTypes,
        loadEventCorrelations,
        loadEventWithPropertyCorrelations,
        addNestedTableExpandedKey,
        removeNestedTableExpandedKey,
    } = useActions(funnelCorrelationLogic(insightProps))

    // Load correlations only if this component is mounted, and then reload if the query changes
    useEffect(() => {
        // We only automatically refresh results when the query changes after the user has manually asked for the first results to be loaded
        if (loadedEventCorrelationsTableOnce) {
            loadEventCorrelations({})
        }
    }, [querySource])

    const { openCorrelationPersonsModal } = useActions(funnelPersonsModalLogic(insightProps))
    const { correlationPropKey } = useValues(funnelCorrelationUsageLogic(insightProps))
    const { reportCorrelationInteraction } = useActions(funnelCorrelationUsageLogic(insightProps))

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
                        <IconTrendUp className="text-success" />
                    ) : (
                        <IconTrendingDown className="text-danger" />
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
                    {capitalizeFirstLetter(aggregationTargetLabel.plural)}{' '}
                    {querySource?.aggregation_group_type_index != undefined ? 'that' : 'who'} converted were{' '}
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
                    <h3 className="mb-1 font-semibold">Loading correlation results…</h3>
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
                        render={(_, record: FunnelCorrelation) => <EventCorrelationActionsCell record={record} />}
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
                        <div className="flex">
                            <LemonCheckbox
                                checked={correlationTypes.includes(FunnelCorrelationType.Success)}
                                onChange={() => onClickCorrelationType(FunnelCorrelationType.Success)}
                                label="Success"
                                size="small"
                                bordered
                            />
                            <LemonCheckbox
                                checked={correlationTypes.includes(FunnelCorrelationType.Failure)}
                                onChange={() => onClickCorrelationType(FunnelCorrelationType.Failure)}
                                label="Drop-off"
                                size="small"
                                bordered
                            />
                        </div>
                    </span>
                </span>
                <ConfigProvider
                    renderEmpty={() =>
                        loadedEventCorrelationsTableOnce ? (
                            <Empty />
                        ) : (
                            <>
                                {/* eslint-disable-next-line react/forbid-dom-props */}
                                <p className="m-auto" style={{ maxWidth: 500 }}>
                                    Highlight events which are likely to have affected the conversion rate within the
                                    funnel.{' '}
                                    <Link to="https://posthog.com/manual/correlation">
                                        Learn more about correlation analysis.
                                    </Link>
                                </p>
                                <LemonButton
                                    onClick={() => loadEventCorrelations({})}
                                    type="secondary"
                                    className="mx-auto mt-2"
                                >
                                    Load results
                                </LemonButton>
                            </>
                        )
                    }
                >
                    <Table
                        dataSource={correlationValues}
                        loading={correlationsLoading}
                        size="small"
                        scroll={{ x: 'max-content' }}
                        rowKey={(record: FunnelCorrelation) => record.event.event}
                        pagination={{
                            pageSize: 5,
                            hideOnSinglePage: true,
                            onChange: () =>
                                reportCorrelationInteraction(FunnelCorrelationResultsType.Events, 'load more'),
                        }}
                        expandable={{
                            expandedRowRender: (record) => renderNestedTable(record.event.event),
                            expandedRowKeys: nestedTableExpandedKeys,
                            rowExpandable: () => querySource?.aggregation_group_type_index === undefined,
                            expandIcon: ({ expanded, onExpand, record, expandable }) => {
                                if (!expandable) {
                                    return null
                                }
                                return expanded ? (
                                    <Tooltip title="Collapse">
                                        <LemonButton
                                            icon={<IconUnfoldLess />}
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
                                            querySource?.aggregation_group_type_index != undefined ? 'that' : 'who'
                                        } performed the event and completed the entire funnel.`}
                                    >
                                        <span>
                                            <IconInfo className="column-info" />
                                        </span>
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
                                                {querySource?.aggregation_group_type_index != undefined
                                                    ? 'that'
                                                    : 'who'}{' '}
                                                performed the event and did <b>not complete</b> the entire funnel.
                                            </>
                                        }
                                    >
                                        <span>
                                            <IconInfo className="column-info" />
                                        </span>
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
                            render={(_, record: FunnelCorrelation) => <EventCorrelationActionsCell record={record} />}
                            width={30}
                        />
                    </Table>
                </ConfigProvider>
            </div>
        </VisibilitySensor>
    ) : null
}
