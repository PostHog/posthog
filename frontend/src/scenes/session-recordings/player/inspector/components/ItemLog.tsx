import clsx from 'clsx'
import { useValues } from 'kea'
import { useMemo } from 'react'

import { IconLive } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { JSONViewer } from 'lib/components/JSONViewer'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { useViewLogsButton } from 'products/logs/frontend/components/ViewLogsButton'

import { ItemTimeDisplay } from '../../../components/ItemTimeDisplay'
import { miniFiltersLogic } from '../miniFiltersLogic'
import { InspectorListItemLog } from '../playerInspectorLogic'
import { ItemLogAttributes } from './ItemLogAttributes'

export interface ItemLogProps {
    item: InspectorListItemLog
    groupCount?: number
    groupedItems?: InspectorListItemLog[]
    sessionId?: string
}

function parseJsonObject(body: string): object | null {
    try {
        const parsed = JSON.parse(body)
        return parsed && typeof parsed === 'object' ? parsed : null
    } catch {
        return null
    }
}

const levelColors: Record<string, string> = {
    trace: 'text-secondary',
    debug: 'text-secondary',
    info: 'text-primary',
    warn: 'text-warning',
    error: 'text-danger',
    fatal: 'text-danger',
}

export function ItemLog({ item, groupCount }: ItemLogProps): JSX.Element {
    const { showLineTooltips } = useValues(miniFiltersLogic)
    const count = groupCount ?? 1
    const showBadge = count > 1

    return (
        <div className="w-full font-light flex items-center" data-attr="item-log">
            <Tooltip title={showLineTooltips ? item.data.body : undefined}>
                <div className="px-2 py-1 text-xs cursor-pointer truncate font-mono flex-1 flex items-center gap-2">
                    <span
                        className={clsx(
                            'uppercase font-semibold text-xxs',
                            levelColors[item.data.level] || 'text-primary'
                        )}
                    >
                        {item.data.level}
                    </span>
                    <span className="truncate">{item.data.body}</span>
                </div>
            </Tooltip>
            {showBadge ? (
                <span
                    className={clsx(
                        'inline-flex items-center justify-center rounded-full min-w-4 h-4 px-0.5 mx-2 shrink-0 text-white text-xxs font-bold',
                        item.highlightColor === 'danger'
                            ? 'bg-fill-error-highlight'
                            : item.highlightColor === 'warning'
                              ? 'bg-fill-warning-highlight'
                              : 'bg-secondary-3000-hover'
                    )}
                >
                    {count}
                </span>
            ) : null}
        </div>
    )
}

export function ItemLogDetail({ item, groupedItems, sessionId }: ItemLogProps): JSX.Element {
    const { onClick: openSessionLogs } = useViewLogsButton({
        sessionId,
        timestamp: item.timestamp.toISOString(),
        openedFrom: 'recording',
    })

    const parsedBody = useMemo(() => parseJsonObject(item.data.body), [item.data.body])
    const serviceName = item.data.resource_attributes?.['service.name'] || item.data.instrumentation_scope

    return (
        <div className="w-full font-light" data-attr="item-log-detail">
            <div className="px-2 py-1 text-xs border-t">
                <div className="flex justify-between items-center mb-2">
                    <LemonLabel>Log</LemonLabel>
                    <LemonButton
                        data-attr="inspector-open-logs"
                        type="tertiary"
                        size="xsmall"
                        icon={<IconLive />}
                        onClick={openSessionLogs}
                        disabledReason={sessionId ? undefined : 'No session ID associated with this log'}
                    >
                        View in Logs
                    </LemonButton>
                </div>

                {groupedItems && groupedItems.length > 1 ? (
                    <>
                        <div className="italic mb-1">
                            This log occurred <b>{groupedItems.length}</b> times:
                        </div>
                        <div className="flex flex-col border rounded bg-surface-primary mb-2 max-h-40 overflow-y-auto">
                            {groupedItems.map((entry, i) => (
                                <div
                                    key={entry.key}
                                    className={clsx('flex items-center gap-2 font-mono', i > 0 && 'border-t')}
                                >
                                    <ItemTimeDisplay
                                        timestamp={entry.timestamp}
                                        timeInRecording={entry.timeInRecording}
                                        className="shrink-0 text-secondary !py-0"
                                    />
                                    <span
                                        className={clsx(
                                            'uppercase font-semibold text-xxs',
                                            levelColors[entry.data.level]
                                        )}
                                    >
                                        {entry.data.level}
                                    </span>
                                    <span className="truncate">{entry.data.body}</span>
                                </div>
                            ))}
                        </div>
                    </>
                ) : null}

                {parsedBody ? (
                    <div className="p-2 bg-bg-light rounded border border-border">
                        <JSONViewer src={parsedBody} collapsed={2} />
                    </div>
                ) : (
                    <CodeSnippet language={Language.Text} wrap thing="log message">
                        {item.data.body}
                    </CodeSnippet>
                )}

                {serviceName ? (
                    <>
                        <LemonDivider dashed />
                        <LemonLabel>Service</LemonLabel>
                        <div className="font-mono text-xs">{serviceName}</div>
                    </>
                ) : null}

                <div className="flex flex-col gap-2 mt-2">
                    <ItemLogAttributes attributes={item.data.attributes} title="Log attributes" />
                    <ItemLogAttributes attributes={item.data.resource_attributes} title="Resource attributes" />
                </div>
            </div>
        </div>
    )
}
