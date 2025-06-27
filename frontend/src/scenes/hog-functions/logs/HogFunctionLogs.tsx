import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDialog, LemonMenu, LemonTag } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { capitalizeFirstLetter } from 'lib/utils'
import { useMemo } from 'react'
import { urls } from 'scenes/urls'

import { hogFunctionTestLogic } from '../configuration/hogFunctionTestLogic'
import { hogFunctionLogsLogic } from './hogFunctionLogsLogic'
import { LogsViewer } from './LogsViewer'
import { GroupedLogEntry, LogsViewerLogicProps } from './logsViewerLogic'
import { hogFunctionConfigurationLogic } from '../configuration/hogFunctionConfigurationLogic'

export function HogFunctionLogs(props: { hogFunctionId: string }): JSX.Element {
    const logicProps: LogsViewerLogicProps = {
        sourceType: 'hog_function',
        sourceId: props.hogFunctionId,
    }

    const { selectingMany, selectedForRetry, retryRunning } = useValues(hogFunctionLogsLogic(logicProps))
    const { setSelectingMany, retrySelectedInvocations, selectAllForRetry } = useActions(
        hogFunctionLogsLogic(logicProps)
    )

    return (
        <>
            <PageHeader
                buttons={
                    <>
                        {!selectingMany ? (
                            <LemonButton size="small" type="secondary" onClick={() => setSelectingMany(true)}>
                                Select invocations
                            </LemonButton>
                        ) : (
                            <>
                                <LemonButton size="small" type="secondary" onClick={() => setSelectingMany(false)}>
                                    Cancel
                                </LemonButton>
                                <LemonButton size="small" type="secondary" onClick={() => selectAllForRetry()}>
                                    Select all
                                </LemonButton>
                                <LemonButton
                                    size="small"
                                    type="primary"
                                    onClick={() => {
                                        LemonDialog.open({
                                            title: 'Retry invocations',
                                            content: `Are you sure you want to retry the selected events? Please don't close the window until the invocations have completed.`,
                                            secondaryButton: {
                                                children: 'Cancel',
                                            },
                                            primaryButton: {
                                                children: 'Retry selected events',
                                                onClick: () => retrySelectedInvocations(),
                                            },
                                        })
                                    }}
                                    loading={retryRunning}
                                    disabledReason={
                                        retryRunning
                                            ? 'Please wait for the current retries to complete.'
                                            : Object.values(selectedForRetry).length === 0
                                            ? 'No invocations selected'
                                            : undefined
                                    }
                                >
                                    Retry selected
                                </LemonButton>
                            </>
                        )}
                    </>
                }
            />
            <LogsViewer
                {...logicProps}
                sourceId={props.hogFunctionId}
                renderColumns={(columns) => {
                    // Add in custom columns for handling retries
                    const newColumns: LemonTableColumns<GroupedLogEntry> = [
                        {
                            title: 'Status',
                            key: 'status',
                            width: 0,
                            render: (_, record) => (
                                <HogFunctionLogsStatus record={record} hogFunctionId={props.hogFunctionId} />
                            ),
                        },
                        ...columns.filter((column) => column.key !== 'logLevel'),
                    ]

                    return newColumns
                }}
            />
        </>
    )
}

type HogFunctionLogsStatus = 'success' | 'failure' | 'running'

function HogFunctionLogsStatus({
    record,
    hogFunctionId,
}: {
    record: GroupedLogEntry
    hogFunctionId: string
}): JSX.Element {
    const logicProps: LogsViewerLogicProps = {
        sourceType: 'hog_function',
        sourceId: hogFunctionId,
    }
    const { loadSampleGlobals, toggleExpanded } = useActions(hogFunctionTestLogic({ id: hogFunctionId }))
    const { contextId } = useValues(hogFunctionConfigurationLogic({ id: hogFunctionId }))

    const { retries, selectingMany, selectedForRetry, eventIdByInvocationId } = useValues(
        hogFunctionLogsLogic(logicProps)
    )
    const { retryInvocations, setSelectingMany, setSelectedForRetry } = useActions(hogFunctionLogsLogic(logicProps))

    const thisRetry = retries[record.instanceId]

    const status = useMemo<HogFunctionLogsStatus>((): HogFunctionLogsStatus => {
        if (thisRetry === 'pending') {
            return 'running'
        }

        const lastEntry = record.entries[record.entries.length - 1]

        if (lastEntry.message.includes('Function completed') || lastEntry.message.includes('Execution successful')) {
            return 'success'
        }

        if (lastEntry.level === 'ERROR') {
            return 'failure'
        }

        return 'running'
    }, [record, thisRetry])

    const eventId = eventIdByInvocationId?.[record.instanceId]

    const internalEvent = ['error-tracking', 'insight-alerts', 'activity-log'].includes(contextId)

    return (
        <div className="flex items-center gap-2">
            {selectingMany ? (
                <LemonCheckbox
                    checked={selectedForRetry[record.instanceId] ?? false}
                    onChange={(checked) => setSelectedForRetry({ [record.instanceId]: checked })}
                />
            ) : null}
            <LemonTag type={status === 'success' ? 'success' : status === 'failure' ? 'danger' : 'warning'}>
                {capitalizeFirstLetter(status)}
            </LemonTag>

            {!internalEvent && (
                <LemonMenu
                    items={[
                        eventId
                            ? {
                                  label: 'View event',
                                  to: urls.event(eventId, ''),
                              }
                            : null,
                        {
                            label: 'Retry event',
                            disabledReason: !eventId ? 'Could not find the source event' : undefined,
                            onClick: () => retryInvocations([record]),
                        },
                        {
                            label: 'Select for retry',
                            onClick: () => {
                                setSelectingMany(true)
                                setSelectedForRetry({
                                    [record.instanceId]: true,
                                })
                            },
                        },
                        {
                            label: 'Test with this event in configuration',
                            onClick: () => {
                                loadSampleGlobals({ eventId })
                                toggleExpanded(true)
                                router.actions.push(urls.hogFunction(hogFunctionId) + '?tab=configuration')
                            },
                        },
                    ]}
                >
                    <LemonButton
                        size="xsmall"
                        icon={<IconEllipsis className="rotate-90" />}
                        loading={thisRetry === 'pending'}
                    />
                </LemonMenu>
            )}
        </div>
    )
}
