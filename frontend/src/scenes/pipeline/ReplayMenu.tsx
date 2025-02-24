import { LemonBanner, LemonButton, LemonDialog, LemonTable, SpinnerOverlay, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { NotFound } from 'lib/components/NotFound'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TZLabel } from 'lib/components/TZLabel'
import { IconRefresh } from 'lib/lemon-ui/icons'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'

import { AvailableFeature, DestinationRetryType } from '~/types'

import { hogFunctionReplayLogic } from './hogFunctionReplayLogic'
import { hogFunctionConfigurationLogic } from './hogfunctions/hogFunctionConfigurationLogic'

export interface HogFunctionConfigurationProps {
    id: string
}

export function ReplayMenu({ id }: HogFunctionConfigurationProps): JSX.Element {
    const logicProps = { id }
    const logic = hogFunctionConfigurationLogic(logicProps)
    const { loading, loaded, showPaygate } = useValues(logic)

    if (loading && !loaded) {
        return <SpinnerOverlay />
    }

    if (!loaded || !id) {
        return <NotFound object="Hog function" />
    }

    if (showPaygate) {
        return <PayGateMini feature={AvailableFeature.DATA_PIPELINES} />
    }

    return (
        <div className="space-y-3">
            <LemonBanner type="info">
                <span>
                    This is a list of all events matching your filters. You can run the function using these historical
                    events.
                </span>
            </LemonBanner>
            <RunsFilters id={id} />
            <ReplayEventsList id={id} />
        </div>
    )
}

function RetryResults({ retry }: { retry: DestinationRetryType }): JSX.Element {
    return (
        <div className="space-y-2" data-attr="test-results">
            <LemonTable
                dataSource={retry.logs ?? []}
                columns={[
                    {
                        title: 'Timestamp',
                        key: 'timestamp',
                        dataIndex: 'timestamp',
                        render: (timestamp) => <TZLabel time={timestamp as string} />,
                        width: 0,
                    },
                    {
                        width: 100,
                        title: 'Level',
                        key: 'level',
                        dataIndex: 'level',
                    },
                    {
                        title: 'Message',
                        key: 'message',
                        dataIndex: 'message',
                        render: (message) => <code className="whitespace-pre-wrap">{message}</code>,
                    },
                ]}
                className="ph-no-capture"
                rowKey="timestamp"
                pagination={{ pageSize: 200, hideOnSinglePage: true }}
            />
        </div>
    )
}

function RunRetryButton({
    loadingRetries,
    row,
    retryHogFunction,
}: {
    loadingRetries: string[]
    row: any
    retryHogFunction: any
}): JSX.Element {
    const handleRetry = (): void => {
        LemonDialog.open({
            title: 'Replay event?',
            description: (
                <>
                    <p>
                        This will execute the hog function using this event. Consider the impact of this function on
                        your destination.
                    </p>
                    <p>
                        <b>Note -</b> do not close this page until the replay is complete.
                    </p>
                </>
            ),
            width: '20rem',
            primaryButton: {
                children: 'Retry',
                onClick: () => retryHogFunction(row),
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }

    return (
        <span className="flex items-center gap-1">
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconRefresh />}
                loading={loadingRetries.includes(row[0].uuid)}
                disabledReason={loadingRetries.includes(row[0].uuid) ? 'Retrying...' : undefined}
                onClick={handleRetry}
            />
        </span>
    )
}

export function RetryStatusIcon({
    retries = [],
    showLabel = false,
}: {
    retries: DestinationRetryType[]
    showLabel?: boolean
}): JSX.Element {
    const colorForStatus = (status: string): 'success' | 'primary' | 'warning' | 'danger' | 'default' => {
        switch (status) {
            case 'success':
                return 'success'
            case 'error':
                return 'danger'
            default:
                return 'default'
        }
    }

    const status = retries.some((retry) => retry.status === 'success') ? 'success' : 'error'
    const color = colorForStatus(status)

    return (
        <Tooltip
            title={
                <>
                    Run status: {status}
                    {retries.length > 1 && (
                        <>
                            <br />
                            Attempts: {retries.length}
                        </>
                    )}
                </>
            }
        >
            <span
                className={clsx(
                    `RetryStatusIcon h-6 p-2 border-2 flex items-center justify-center rounded-full font-semibold text-xs select-none`,
                    color === 'primary' && 'RetryStatusIcon--pulse',
                    showLabel ? '' : 'w-6',
                    retries.length > 0 ? `border-${color} text-${color}-dark` : ''
                )}
            >
                {showLabel ? <span className="text-center">{status}</span> : retries.length}
            </span>
        </Tooltip>
    )
}

function EmptyColumn(): JSX.Element {
    return (
        <Tooltip title="NULL" placement="right" delayMs={0}>
            <span className="cursor-default" aria-hidden>
                —
            </span>
        </Tooltip>
    )
}

function RunsFilters({ id }: { id: string }): JSX.Element {
    const logic = hogFunctionReplayLogic({ id })
    const { eventsLoading, baseEventsQuery } = useValues(logic)
    const { loadEvents, changeDateRange, loadTotalEvents } = useActions(logic)

    const handleRefresh = (): void => {
        loadEvents()
        loadTotalEvents()
    }

    return (
        <div className="flex items-center gap-2">
            <LemonButton
                onClick={handleRefresh}
                loading={eventsLoading}
                type="secondary"
                icon={<IconRefresh />}
                size="small"
            >
                Refresh
            </LemonButton>
            <DateFilter
                dateFrom={baseEventsQuery?.after ?? undefined}
                dateTo={baseEventsQuery?.before ?? undefined}
                onChange={changeDateRange}
            />
        </div>
    )
}

export function ReplayEventsList({ id }: { id: string }): JSX.Element | null {
    const logic = hogFunctionReplayLogic({ id })
    const { eventsLoading, eventsWithRetries, loadingRetries, totalEvents, pageTimestamps } = useValues(logic)
    const { retryHogFunction, loadNextEventsPage, loadPreviousEventsPage } = useActions(logic)

    return (
        <LemonTable
            dataSource={eventsWithRetries}
            loading={eventsLoading}
            loadingSkeletonRows={5}
            pagination={{
                controlled: true,
                currentPage: pageTimestamps.length + 1,
                onForward: loadNextEventsPage,
                onBackward: loadPreviousEventsPage,
                pageSize: eventsWithRetries.length,
                hideOnSinglePage: false,
                entryCount: totalEvents,
            }}
            expandable={{
                noIndent: true,
                expandedRowRender: ([, , , retries]) => {
                    return (
                        <LemonTable
                            dataSource={retries}
                            embedded={true}
                            columns={[
                                {
                                    title: 'Status',
                                    key: 'status',
                                    width: 0,
                                    render: (_, retry) => {
                                        return false ? (
                                            <LemonBanner type={retry.status === 'success' ? 'success' : 'error'}>
                                                {retry.status === 'success' ? 'Success' : 'Error'}
                                            </LemonBanner>
                                        ) : (
                                            <RetryStatusIcon retries={[retry]} showLabel />
                                        )
                                    },
                                },
                                {
                                    title: 'Test invocation logs',
                                    key: 'testInvocationLogs',
                                    render: (_, retry) => <RetryResults retry={retry} />,
                                },
                            ]}
                        />
                    )
                },
            }}
            columns={[
                {
                    key: 'retries',
                    title: 'Retries',
                    width: 0,
                    render: (_, [, , , retries]) => {
                        return <RetryStatusIcon retries={retries} />
                    },
                },
                {
                    title: 'Event',
                    key: 'event',
                    className: 'max-w-80',
                    render: (_, [event]) => {
                        return event.event ? (
                            <PropertyKeyInfo value={event.event} type={TaxonomicFilterGroupType.Events} />
                        ) : (
                            <EmptyColumn />
                        )
                    },
                },
                {
                    title: 'Person',
                    key: 'person',
                    render: (_, [, person]) => {
                        return person ? <PersonDisplay person={person} withIcon /> : <EmptyColumn />
                    },
                },
                {
                    title: 'URL / Screen',
                    key: 'url',
                    className: 'max-w-80',
                    render: (_, [event]) =>
                        event.properties['$current_url'] || event.properties['$screen_name'] ? (
                            <span>{event.properties['$current_url'] || event.properties['$screen_name']}</span>
                        ) : (
                            <EmptyColumn />
                        ),
                },
                {
                    title: 'Library',
                    key: 'library',
                    className: 'max-w-80',
                    render: (_, [event]) => {
                        return event.properties['$lib'] ? <span>{event.properties['$lib']}</span> : <EmptyColumn />
                    },
                },
                {
                    title: 'Time',
                    key: 'time',
                    className: 'max-w-80',
                    render: (_, [event]) => {
                        return event.timestamp ? <TZLabel time={event.timestamp} /> : <EmptyColumn />
                    },
                },
                {
                    key: 'actions',
                    width: 0,
                    render: function RenderActions(_, row) {
                        return (
                            <div className="flex gap-1">
                                <RunRetryButton
                                    loadingRetries={loadingRetries}
                                    row={row}
                                    retryHogFunction={retryHogFunction}
                                />
                            </div>
                        )
                    },
                },
            ]}
            emptyState={<InsightEmptyState />}
        />
    )
}
