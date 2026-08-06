import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDialog, LemonMenu, LemonTag } from '@posthog/lemon-ui'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { hogFunctionLogsLogic } from 'scenes/hog-functions/logs/hogFunctionLogsLogic'
import { LogsViewer } from 'scenes/hog-functions/logs/LogsViewer'
import { GroupedLogEntry, LogsViewerLogicProps } from 'scenes/hog-functions/logs/logsViewerLogic'
import { renderHogFunctionMessage } from 'scenes/hog-functions/logs/renderHogFunctionMessage'
import { urls } from 'scenes/urls'

export function WebhookLogsSection({ hogFunctionId }: { hogFunctionId: string }): JSX.Element {
    const logsLogicProps: LogsViewerLogicProps = {
        sourceType: 'hog_function',
        sourceId: hogFunctionId,
    }
    const logic = hogFunctionLogsLogic(logsLogicProps)

    const { selectingMany, selectedForRetry, retryRunning } = useValues(logic)
    const { setSelectingMany, retrySelectedInvocations, selectAllForRetry } = useActions(logic)

    return (
        <LemonCard hoverEffect={false} className="space-y-3">
            <div className="flex items-center justify-between gap-2">
                <div>
                    <h3 className="text-lg font-semibold mb-0">Logs</h3>
                    <p className="text-muted text-xs mb-0">
                        Inspect received webhook requests and retry failed events.
                    </p>
                </div>
                {selectingMany ? (
                    <div className="flex gap-2 items-center">
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
                                    title: 'Retry events',
                                    content: `Are you sure you want to retry the selected events? Please don't close the window until the retries have completed.`,
                                    secondaryButton: { children: 'Cancel' },
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
                                      ? 'No events selected'
                                      : undefined
                            }
                        >
                            Retry selected
                        </LemonButton>
                    </div>
                ) : null}
            </div>
            <LogsViewer
                {...logsLogicProps}
                instanceLabel="request"
                renderColumns={(columns) => {
                    const newColumns: LemonTableColumns<GroupedLogEntry> = [
                        {
                            title: 'Status',
                            key: 'status',
                            width: 0,
                            render: (_, record) => <WebhookLogStatus record={record} hogFunctionId={hogFunctionId} />,
                        },
                        ...columns.filter((column) => column.key !== 'logLevel'),
                    ]
                    return newColumns
                }}
                renderMessage={renderHogFunctionMessage}
            />
        </LemonCard>
    )
}

type WebhookLogStatusType = 'success' | 'failure' | 'running'

function WebhookLogStatus({ record, hogFunctionId }: { record: GroupedLogEntry; hogFunctionId: string }): JSX.Element {
    const logicProps: LogsViewerLogicProps = {
        sourceType: 'hog_function',
        sourceId: hogFunctionId,
    }
    const logic = hogFunctionLogsLogic(logicProps)
    const { retries, selectingMany, selectedForRetry, eventIdByInvocationId } = useValues(logic)
    const { retryInvocations, setSelectingMany, setSelectedForRetry } = useActions(logic)

    const thisRetry = retries[record.instanceId]

    const status = useMemo<WebhookLogStatusType>((): WebhookLogStatusType => {
        if (thisRetry === 'pending') {
            return 'running'
        }
        if (
            record.entries.some(
                (e) => e.message.includes('Function completed') || e.message.includes('Execution successful')
            )
        ) {
            return 'success'
        }
        if (record.entries.some((e) => e.level === 'ERROR')) {
            return 'failure'
        }
        return 'running'
    }, [record, thisRetry])

    const eventId = eventIdByInvocationId?.[record.instanceId]

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
                            setSelectedForRetry({ [record.instanceId]: true })
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
        </div>
    )
}
