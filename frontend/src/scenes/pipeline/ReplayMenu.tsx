import {
    LemonBanner,
    LemonButton,
    LemonDialog,
    LemonDivider,
    LemonTable,
    SpinnerOverlay,
    Tooltip,
} from '@posthog/lemon-ui'
import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TZLabel } from 'lib/components/TZLabel'
import { IconRefresh } from 'lib/lemon-ui/icons'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'

import { AvailableFeature } from '~/types'

import { hogFunctionReplayLogic } from './hogFunctionReplayLogic'
import { hogFunctionConfigurationLogic } from './hogfunctions/hogFunctionConfigurationLogic'

export interface HogFunctionConfigurationProps {
    templateId?: string | null
    id?: string | null

    displayOptions?: {
        embedded?: boolean
        hidePageHeader?: boolean
        hideOverview?: boolean
        showFilters?: boolean
        showExpectedVolume?: boolean
        showStatus?: boolean
        showEnabled?: boolean
        showTesting?: boolean
        canEditSource?: boolean
        showPersonsCount?: boolean
    }
}

export function ReplayMenu({ templateId, id, displayOptions = {} }: HogFunctionConfigurationProps): JSX.Element {
    const logicProps = { templateId, id }
    const logic = hogFunctionConfigurationLogic(logicProps)
    const {
        isConfigurationSubmitting,
        configurationChanged,
        configuration,
        loading,
        loaded,
        hogFunction,
        willReEnableOnSave,
        willChangeEnabledOnSave,
        showPaygate,
        template,
        type,
    } = useValues(logic)
    const { submitConfiguration, resetForm, duplicate, deleteHogFunction } = useActions(logic)

    if (loading && !loaded) {
        return <SpinnerOverlay />
    }

    if (!loaded || !id) {
        return <NotFound object="Hog function" />
    }

    const isLegacyPlugin = (template?.id || hogFunction?.template?.id)?.startsWith('plugin-')

    const headerButtons = (
        <>
            {!templateId && (
                <>
                    <More
                        overlay={
                            <>
                                {!isLegacyPlugin && (
                                    <LemonButton fullWidth onClick={() => duplicate()}>
                                        Duplicate
                                    </LemonButton>
                                )}
                                <LemonDivider />
                                <LemonButton status="danger" fullWidth onClick={() => deleteHogFunction()}>
                                    Delete
                                </LemonButton>
                            </>
                        }
                    />
                    <LemonDivider vertical />
                </>
            )}
        </>
    )

    const saveButtons = (
        <>
            {configurationChanged ? (
                <LemonButton
                    type="secondary"
                    htmlType="reset"
                    onClick={() => resetForm()}
                    disabledReason={
                        !configurationChanged
                            ? 'No changes'
                            : isConfigurationSubmitting
                            ? 'Saving in progress…'
                            : undefined
                    }
                >
                    Clear changes
                </LemonButton>
            ) : null}
            <LemonButton
                type="primary"
                htmlType="submit"
                onClick={submitConfiguration}
                loading={isConfigurationSubmitting}
            >
                <span>{templateId ? 'Create' : 'Save'}</span>
                <span>
                    {willReEnableOnSave
                        ? ' & re-enable'
                        : willChangeEnabledOnSave
                        ? ` & ${configuration.enabled ? 'enable' : 'disable'}`
                        : ''}
                </span>
            </LemonButton>
        </>
    )

    if (showPaygate) {
        return <PayGateMini feature={AvailableFeature.DATA_PIPELINES} />
    }

    const includeHeaderButtons = !(displayOptions.hidePageHeader ?? false)
    const showExpectedVolume = displayOptions.showExpectedVolume ?? ['destination', 'site_destination'].includes(type)

    return (
        <div className="space-y-3">
            <LemonBanner type="info">
                <span>
                    This is a list of all events matching your filters. You can run the function using these historical
                    events.
                </span>
            </LemonBanner>
            <RunsFilters id={id} />
            <BindLogic logic={hogFunctionConfigurationLogic} props={logicProps}>
                {includeHeaderButtons && (
                    <PageHeader
                        buttons={
                            <>
                                {headerButtons}
                                {saveButtons}
                            </>
                        }
                    />
                )}

                {hogFunction?.filters?.bytecode_error ? (
                    <div>
                        <LemonBanner type="error">
                            <b>Error saving filters:</b> {hogFunction.filters.bytecode_error}
                        </LemonBanner>
                    </div>
                ) : null}

                {showExpectedVolume ? <HogFunctionEventEstimates id={id} /> : null}
            </BindLogic>
        </div>
    )
}

function RetryResults({ retry }: { retry: any }): JSX.Element {
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
    retries: any[]
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

export function HogFunctionEventEstimates({ id }: { id: string }): JSX.Element | null {
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
