import { IconEllipsis } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonDialog,
    LemonDropdown,
    LemonMenu,
    LemonTable,
    LemonTag,
    LemonTagType,
    SpinnerOverlay,
    Tooltip,
} from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TZLabel } from 'lib/components/TZLabel'
import { IconRefresh } from 'lib/lemon-ui/icons'
import { capitalizeFirstLetter } from 'lib/utils'
import { useState } from 'react'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { urls } from 'scenes/urls'

import { AvailableFeature, CyclotronJobInvocationGlobals, GroupType, GroupTypeIndex, LogEntry } from '~/types'

import {
    convertToHogFunctionInvocationGlobals,
    hogFunctionConfigurationLogic,
} from '../configuration/hogFunctionConfigurationLogic'
import { hogFunctionTestLogic } from '../configuration/hogFunctionTestLogic'
import { HogFunctionFilters } from '../filters/HogFunctionFilters'
import { tagTypeForLevel } from '../logs/LogsViewer'
import {
    CyclotronJobTestInvocationResultWithEventId,
    hogFunctionTestingLogic,
    HogFunctionTestingLogicProps,
} from './hogFunctionTestingLogic'

const buildGlobals = (
    row: any,
    groupTypes: Map<GroupTypeIndex, GroupType>,
    hogFunctionName: string
): CyclotronJobInvocationGlobals => {
    const globals = convertToHogFunctionInvocationGlobals(row[0], row[1])
    globals.groups = {}
    groupTypes.forEach((groupType, index) => {
        const tuple = row?.[4 + index]
        if (tuple && Array.isArray(tuple) && tuple[2]) {
            let properties = {}
            try {
                properties = JSON.parse(tuple[3])
            } catch {
                // Ignore
            }
            globals.groups![groupType.group_type] = {
                type: groupType.group_type,
                index: tuple[1],
                id: tuple[2], // TODO: rename to "key"?
                url: `${window.location.origin}/groups/${tuple[1]}/${encodeURIComponent(tuple[2])}`,
                properties,
            }
        }
    })
    globals.source = {
        name: hogFunctionName ?? 'Unnamed',
        url: window.location.href.split('#')[0],
    }

    return globals
}

export function HogFunctionTesting({ id }: HogFunctionTestingLogicProps): JSX.Element {
    const { selectingMany, eventsWithRetries, loadingRetries, selectedForRetry } = useValues(
        hogFunctionTestingLogic({ id })
    )
    const { setSelectingMany, retryInvocation, selectForRetry, deselectForRetry, resetSelectedForRetry } = useActions(
        hogFunctionTestingLogic({ id })
    )
    const {
        loading,
        loaded,
        showPaygate,
        groupTypes,
        configuration,
        isConfigurationSubmitting,
        willReEnableOnSave,
        willChangeEnabledOnSave,
        configurationChanged,
    } = useValues(hogFunctionConfigurationLogic({ id }))
    const { submitConfiguration } = useActions(hogFunctionConfigurationLogic({ id }))

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
        <div className="deprecated-space-y-3">
            <PageHeader
                buttons={
                    <>
                        {!selectingMany ? (
                            <LemonButton size="small" type="secondary" onClick={() => setSelectingMany(true)}>
                                Select invocations
                            </LemonButton>
                        ) : (
                            <>
                                <LemonButton
                                    size="small"
                                    type="secondary"
                                    onClick={() => {
                                        setSelectingMany(false)
                                        resetSelectedForRetry()
                                    }}
                                >
                                    Cancel
                                </LemonButton>
                                <LemonButton
                                    size="small"
                                    type="secondary"
                                    onClick={() =>
                                        selectedForRetry.length === eventsWithRetries.length
                                            ? deselectForRetry(eventsWithRetries.map((row) => row[0].uuid))
                                            : selectForRetry(eventsWithRetries.map((row) => row[0].uuid))
                                    }
                                >
                                    <span>
                                        {selectedForRetry.length === eventsWithRetries.length
                                            ? 'Deselect all'
                                            : 'Select all'}
                                    </span>
                                </LemonButton>
                                <LemonButton
                                    size="small"
                                    type="primary"
                                    onClick={() => {
                                        LemonDialog.open({
                                            title: 'Test selected events',
                                            content: `Are you sure you want to test the selected events? Please don't close the window until the invocations have completed.`,
                                            secondaryButton: {
                                                children: 'Cancel',
                                            },
                                            primaryButton: {
                                                children: 'Test selected events',
                                                onClick: () => {
                                                    eventsWithRetries
                                                        .filter((row) => selectedForRetry.includes(row[0].uuid))
                                                        .forEach((row) =>
                                                            retryInvocation({
                                                                eventId: row[0].uuid,
                                                                globals: buildGlobals(
                                                                    row,
                                                                    groupTypes,
                                                                    configuration?.name ?? 'Unnamed'
                                                                ),
                                                            })
                                                        )
                                                },
                                            },
                                        })
                                    }}
                                    loading={loadingRetries.length > 0}
                                    disabledReason={
                                        loadingRetries.length > 0
                                            ? 'Please wait for the current tests to complete.'
                                            : selectedForRetry.length === 0
                                            ? 'No invocations selected'
                                            : undefined
                                    }
                                >
                                    Test selected
                                </LemonButton>
                            </>
                        )}
                        {configurationChanged ? (
                            <LemonButton
                                type="primary"
                                htmlType="submit"
                                onClick={submitConfiguration}
                                loading={isConfigurationSubmitting}
                            >
                                Save
                                {willReEnableOnSave
                                    ? ' & re-enable'
                                    : willChangeEnabledOnSave
                                    ? ` & ${configuration.enabled ? 'enable' : 'disable'}`
                                    : ''}
                            </LemonButton>
                        ) : null}
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

export function RetryStatusIcon({
    retries = [],
    showLabel = false,
}: {
    retries: CyclotronJobTestInvocationResultWithEventId[]
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
    const [dropdownOpen, setDropdownOpen] = useState(false)

    const handleRefresh = (): void => {
        loadEvents()
        loadTotalEvents()
    }

    return (
        <div className="flex gap-2 items-center">
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
            <LemonDropdown
                visible={dropdownOpen}
                closeOnClickInside={false}
                matchWidth={false}
                placement="right-end"
                overlay={
                    <Form
                        logic={hogFunctionConfigurationLogic}
                        props={{ id }}
                        formKey="configuration"
                        className="deprecated-space-y-3"
                    >
                        <HogFunctionFilters embedded={true} />
                        <div className="flex justify-end mt-2">
                            <LemonButton size="small" type="primary" onClick={() => setDropdownOpen(false)}>
                                Done
                            </LemonButton>
                        </div>
                    </Form>
                }
            >
                <LemonButton size="small" type="secondary" onClick={() => setDropdownOpen((v) => !v)}>
                    Filters
                </LemonButton>
            </LemonDropdown>
        </div>
    )
}

function TestingEventsList({ id }: { id: string }): JSX.Element | null {
    const logic = hogFunctionTestingLogic({ id })
    const {
        eventsLoading,
        eventsWithRetries,
        totalEvents,
        pageTimestamps,
        expandedRows,
        loadingRetries,
        selectingMany,
        selectedForRetry,
    } = useValues(logic)
    const {
        retryInvocation,
        loadNextEventsPage,
        loadPreviousEventsPage,
        expandRow,
        collapseRow,
        selectForRetry,
        deselectForRetry,
    } = useActions(logic)
    const { groupTypes, configuration, logicProps } = useValues(hogFunctionConfigurationLogic({ id }))
    const { setSampleGlobals, toggleExpanded } = useActions(hogFunctionTestLogic(logicProps))

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
                                (acc: LogEntry[], group: CyclotronJobTestInvocationResultWithEventId) =>
                                    acc.concat(group.logs),
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
                            <div className="flex gap-2 items-center">
                                {selectingMany ? (
                                    <LemonCheckbox
                                        checked={selectedForRetry.includes(eventId)}
                                        onChange={(checked) => {
                                            if (checked) {
                                                selectForRetry([eventId])
                                            } else {
                                                deselectForRetry([eventId])
                                            }
                                        }}
                                    />
                                ) : null}

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
                                            onClick: () => {
                                                retryInvocation({
                                                    eventId,
                                                    globals: buildGlobals(
                                                        row,
                                                        groupTypes,
                                                        configuration?.name ?? 'Unnamed'
                                                    ),
                                                })
                                                expandRow(eventId)
                                            },
                                        },
                                        {
                                            label: 'Test with this event in configuration',
                                            onClick: () => {
                                                const globals = buildGlobals(
                                                    row,
                                                    groupTypes,
                                                    configuration?.name ?? 'Unnamed'
                                                )
                                                setSampleGlobals(globals)
                                                toggleExpanded(true)
                                                router.actions.push(urls.hogFunction(id) + '?tab=configuration')
                                            },
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
