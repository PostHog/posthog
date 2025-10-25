import './FunnelCorrelationTable.scss'

import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconArchive, IconTrending } from '@posthog/icons'
import { LemonCheckbox, LemonTable } from '@posthog/lemon-ui'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { VisibilitySensor } from 'lib/components/VisibilitySensor/VisibilitySensor'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { IconSelectEvents, IconTrendingDown } from 'lib/lemon-ui/icons'
import { capitalizeFirstLetter } from 'lib/utils'
import { ValueInspectorButton } from 'scenes/funnels/ValueInspectorButton'
import { funnelCorrelationLogic } from 'scenes/funnels/funnelCorrelationLogic'
import { funnelCorrelationUsageLogic } from 'scenes/funnels/funnelCorrelationUsageLogic'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { funnelPersonsModalLogic } from 'scenes/funnels/funnelPersonsModalLogic'
import { parseDisplayNameForCorrelation } from 'scenes/funnels/funnelUtils'
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
    }, [querySource, loadedEventCorrelationsTableOnce, loadEventCorrelations])

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
                <div className="font-semibold text-text-3000">
                    {is_success ? (
                        <IconTrending className="text-success" />
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
                </div>
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
                    <p className="m-0 text-xs text-secondary">This process can take up to 20 seconds.</p>
                </div>
            )
        }

        return (
            <div className="p-4">
                <h4 className="pl-4">Correlated properties</h4>
                <LemonTable
                    id={`event-correlation__${eventName}`}
                    dataSource={eventWithPropertyCorrelationsValues[eventName]}
                    rowKey={(record: FunnelCorrelation) => 'nested' + record.event.event}
                    pagination={{
                        pageSize: 5,
                        hideOnSinglePage: true,
                        onBackward: () =>
                            reportCorrelationInteraction(
                                FunnelCorrelationResultsType.EventWithProperties,
                                'pagination change',
                                { direction: 'backward', page_size: 5 }
                            ),
                        onForward: () =>
                            reportCorrelationInteraction(
                                FunnelCorrelationResultsType.EventWithProperties,
                                'pagination change',
                                { direction: 'forward', page_size: 5 }
                            ),
                    }}
                    columns={[
                        {
                            title: 'Property',
                            key: 'eventName',
                            render: (_, record) => renderOddsRatioTextRecord(record),
                        },
                        {
                            title: 'Completed',
                            key: 'success_count',
                            render: (_, record) => renderSuccessCount(record),
                            width: 90,
                            align: 'center',
                        },
                        {
                            title: 'Dropped off',
                            key: 'failure_count',
                            render: (_, record) => renderFailureCount(record),
                            width: 120,
                            align: 'center',
                        },
                        {
                            key: 'actions',
                            width: 30,
                            align: 'center',
                            render: (_, record) => <EventCorrelationActionsCell record={record} />,
                        },
                    ]}
                />
            </div>
        )
    }

    return steps.length > 1 ? (
        <VisibilitySensor id={correlationPropKey} offset={152}>
            <div className="FunnelCorrelationTable mt-4 border rounded overflow-hidden">
                <span className="flex px-2 py-1 bg-[var(--color-bg-table)]">
                    <span className="flex items-center text-xs font-bold">
                        <IconSelectEvents className="mr-1 text-2xl opacity-50" />
                        CORRELATED EVENTS
                    </span>
                    <span className="table-options flex grow items-center justify-end">
                        <p className="flex items-center m-1 font-sans text-xs text-secondary font-semibold">
                            CORRELATION
                        </p>
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
                <CorrelationMatrix />

                <LemonTable
                    id="event-correlation"
                    embedded
                    columns={[
                        {
                            title: 'Event',
                            key: 'eventName',
                            render: (_, record) => renderOddsRatioTextRecord(record),
                        },
                        {
                            title: 'Completed',
                            tooltip: `${capitalizeFirstLetter(aggregationTargetLabel.plural)} ${
                                querySource?.aggregation_group_type_index != undefined ? 'that' : 'who'
                            } performed the event and completed the entire funnel.`,
                            dataIndex: 'success_count',
                            render: (_, record) => renderSuccessCount(record),
                            align: 'center',
                            width: 90,
                        },
                        {
                            title: 'Dropped off',
                            dataIndex: 'failure_count',
                            tooltip: `${capitalizeFirstLetter(aggregationTargetLabel.plural)} ${
                                querySource?.aggregation_group_type_index != undefined ? 'that' : 'who'
                            } performed the event and did not complete the entire funnel.`,
                            render: (_, record) => renderFailureCount(record),
                            align: 'center',
                            width: 120,
                        },
                        {
                            key: 'actions',
                            width: 30,
                            render: (_, record: FunnelCorrelation) => <EventCorrelationActionsCell record={record} />,
                        },
                    ]}
                    dataSource={correlationValues}
                    emptyState={
                        <div className="p-4 m-auto max-w-140">
                            <div className="flex flex-col items-center justify-self-center text-center">
                                {loadedEventCorrelationsTableOnce ? (
                                    <div className="flex flex-col items-center justify-center deprecated-space-y-1 min-h-24">
                                        <IconArchive className="text-tertiary-hover text-2xl" />
                                        <div>No correlated events found.</div>
                                    </div>
                                ) : (
                                    <>
                                        <p className="m-auto">
                                            Highlight events which are likely to have affected the conversion rate
                                            within the funnel.{' '}
                                            <Link to="https://posthog.com/docs/product-analytics/correlation">
                                                Learn more about correlation analysis.
                                            </Link>
                                        </p>
                                        <LemonButton
                                            onClick={() => loadEventCorrelations({})}
                                            type="secondary"
                                            className="mx-auto !mt-2"
                                        >
                                            Load results
                                        </LemonButton>
                                    </>
                                )}
                            </div>
                        </div>
                    }
                    loading={correlationsLoading}
                    size="small"
                    rowKey={(record) => record.event.event}
                    pagination={{
                        pageSize: 5,
                        hideOnSinglePage: true,
                        onBackward: () =>
                            reportCorrelationInteraction(FunnelCorrelationResultsType.Events, 'load more'),
                        onForward: () => reportCorrelationInteraction(FunnelCorrelationResultsType.Events, 'load more'),
                    }}
                    expandable={{
                        expandedRowRender: (record) => renderNestedTable(record.event.event),
                        isRowExpanded: (record) => nestedTableExpandedKeys.includes(record.event.event),
                        rowExpandable: () => querySource?.aggregation_group_type_index === undefined,
                        onRowExpand: (record) => {
                            !eventHasPropertyCorrelations(record.event.event) &&
                                loadEventWithPropertyCorrelations(record.event.event)
                            addNestedTableExpandedKey(record.event.event)
                        },
                        onRowCollapse: (record) => {
                            removeNestedTableExpandedKey(record.event.event)
                        },
                    }}
                />
            </div>
        </VisibilitySensor>
    ) : null
}
