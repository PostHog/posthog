import { IconEllipsis } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDialog,
    LemonMenu,
    LemonTable,
    LemonTag,
    LemonTagType,
    SpinnerOverlay,
    Tooltip,
} from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TZLabel } from 'lib/components/TZLabel'
import { IconRefresh } from 'lib/lemon-ui/icons'
import { capitalizeFirstLetter } from 'lib/utils'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { urls } from 'scenes/urls'

import { AvailableFeature, DestinationRetryType, LogEntry } from '~/types'

import { HogFunctionFilters } from './hogfunctions/filters/HogFunctionFilters'
import { hogFunctionConfigurationLogic } from './hogfunctions/hogFunctionConfigurationLogic'
import { tagTypeForLevel } from './hogfunctions/logs/LogsViewer'
import { hogFunctionTestingLogic } from './hogFunctionTestingLogic'

export interface HogFunctionTestingProps {
    id: string
}

export function TestingMenu({ id }: HogFunctionTestingProps): JSX.Element {
    const { eventsWithRetries, loadingRetries } = useValues(hogFunctionTestingLogic({ id }))
    const { retryInvocation } = useActions(hogFunctionTestingLogic({ id }))
    const { loading, loaded, showPaygate } = useValues(hogFunctionConfigurationLogic({ id }))

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
            <PageHeader
                buttons={
                    <>
                        <RetryButton
                            loadingRetries={loadingRetries}
                            rows={eventsWithRetries}
                            retryHogFunction={retryInvocation}
                            eventIds={eventsWithRetries.map((row) => row[0].uuid)}
                        />
                    </>
                }
            />
            <LemonBanner type="info">
                <span>
                    This is a list of all events matching your filters. You can run the function using these historical
                    events.
                </span>
            </LemonBanner>
            <RunsFilters id={id} />
            <TestingEventsList id={id} />
        </div>
    )
}

function RetryButton({
    loadingRetries,
    rows,
    retryHogFunction,
    eventIds,
}: {
    loadingRetries: string[]
    rows: any[]
    retryHogFunction: (row: any) => void
    eventIds: string[]
}): JSX.Element {
    const handleRetry = (): void => {
        LemonDialog.open({
            title: 'Test events?',
            description: (
                <>
                    <p>
                        This will invoke the hog function for all visible events. Consider the impact of this function
                        on your destination.
                    </p>
                    <p>
                        <b>Note -</b> do not close this page until all events have been tested.
                    </p>
                </>
            ),
            width: '20rem',
            primaryButton: {
                children: 'Retry',
                onClick: () => {
                    rows.map((row) => retryHogFunction(row))
                },
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }

    return (
        <LemonButton
            size="small"
            type={rows.length > 1 ? 'primary' : 'secondary'}
            icon={rows.length > 1 ? null : <IconRefresh />}
            loading={loadingRetries.some((retry) => eventIds.includes(retry))}
            disabledReason={loadingRetries.some((retry) => eventIds.includes(retry)) ? 'Retrying...' : undefined}
            onClick={handleRetry}
        >
            {rows.length > 1 ? <span>Test all visible events</span> : null}
        </LemonButton>
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
    const logic = hogFunctionTestingLogic({ id })
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
            <HogFunctionFilters />
        </div>
    )
}

export function TestingEventsList({ id }: { id: string }): JSX.Element | null {
    const logic = hogFunctionTestingLogic({ id })
    const { eventsLoading, eventsWithRetries, totalEvents, pageTimestamps, expandedRows, loadingRetries } =
        useValues(logic)
    const { retryInvocation, loadNextEventsPage, loadPreviousEventsPage, expandRow, collapseRow } = useActions(logic)

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
                isRowExpanded: ([event]) => expandedRows.includes(event.uuid),
                onRowExpand: ([event]) => expandRow(event.uuid),
                onRowCollapse: ([event]) => collapseRow(event.uuid),
                noIndent: true,
                expandedRowRender: ([, , , retries]) => {
                    return (
                        <LemonTable
                            dataSource={retries.reduce(
                                (acc: LogEntry[], group: DestinationRetryType) => acc.concat(group.logs),
                                []
                            )}
                            embedded={true}
                            columns={[
                                {
                                    key: 'spacer',
                                    width: 0,
                                    render: () => <div className="w-6" />,
                                },
                                {
                                    title: 'Timestamp',
                                    key: 'timestamp',
                                    dataIndex: 'timestamp',
                                    render: (_, { timestamp }) => <TZLabel time={timestamp} />,
                                },
                                {
                                    title: 'Level',
                                    key: 'level',
                                    dataIndex: 'level',
                                    render: (_, { level }) => (
                                        <LemonTag type={tagTypeForLevel(level)}>{level.toUpperCase()}</LemonTag>
                                    ),
                                },
                                {
                                    title: 'Message',
                                    key: 'message',
                                    dataIndex: 'message',
                                    render: (_, { message }) => <code className="whitespace-pre-wrap">{message}</code>,
                                },
                            ]}
                        />
                    )
                },
            }}
            columns={[
                {
                    title: 'Status',
                    key: 'status',
                    width: 0,
                    render: (_, row) => {
                        const eventId = row[0].uuid

                        const getStatus = (): { text: string; type: LemonTagType } => {
                            if (loadingRetries.includes(eventId)) {
                                return {
                                    text: 'Running',
                                    type: 'warning',
                                }
                            } else if (row[3].length === 0) {
                                return {
                                    text: 'Not tested',
                                    type: 'muted',
                                }
                            } else if (row[3][row[3].length - 1].status === 'error') {
                                return {
                                    text: 'Failure',
                                    type: 'danger',
                                }
                            } else if (row[3][row[3].length - 1].status === 'success') {
                                return {
                                    text: 'Success',
                                    type: 'success',
                                }
                            }
                            return {
                                text: 'Unknown',
                                type: 'muted',
                            }
                        }

                        return (
                            <div className="flex items-center gap-2">
                                <LemonTag type={getStatus().type}>{capitalizeFirstLetter(getStatus().text)}</LemonTag>

                                <LemonMenu
                                    items={[
                                        eventId
                                            ? {
                                                  label: 'View event',
                                                  to: urls.event(eventId, row[0].timestamp),
                                              }
                                            : null,
                                        {
                                            label: 'Test event',
                                            disabledReason: !eventId ? 'Could not find the source event' : undefined,
                                            onClick: () => retryInvocation(row),
                                        },
                                    ]}
                                >
                                    <LemonButton
                                        size="xsmall"
                                        icon={<IconEllipsis className="rotate-90" />}
                                        loading={loadingRetries.includes(eventId) ? true : undefined}
                                    />
                                </LemonMenu>
                            </div>
                        )
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
            ]}
            emptyState={<InsightEmptyState />}
        />
    )
}
