import clsx from 'clsx'
import { useValues } from 'kea'

import { LemonDivider } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { SimpleKeyValueList } from 'lib/components/SimpleKeyValueList'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { colonDelimitedDuration } from 'lib/utils'

import { miniFiltersLogic } from '../miniFiltersLogic'
import { InspectorListItemAppState, InspectorListItemConsole } from '../playerInspectorLogic'

export interface ItemConsoleLogProps {
    item: InspectorListItemConsole
}

export interface ItemAppStateProps {
    item: InspectorListItemAppState
}

export function ItemConsoleLog({ item }: ItemConsoleLogProps): JSX.Element {
    const { groupRepeatedItems } = useValues(miniFiltersLogic)
    const showBadge = groupRepeatedItems && (item.data.count || 1) > 1

    return (
        <div className="w-full font-light flex items-center" data-attr="item-console-log">
            <div className="px-2 py-1 text-xs cursor-pointer truncate font-mono flex-1">{item.data.content}</div>
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
                    {item.data.count}
                </span>
            ) : null}
        </div>
    )
}

export function ItemConsoleLogDetail({ item }: ItemConsoleLogProps): JSX.Element {
    const count = item.data.count || 1
    const occurrences = item.data.occurrences
    const firstTimestamp = occurrences?.[0] ?? item.data.timestamp

    return (
        <div className="w-full font-light" data-attr="item-console-log">
            <div className="px-2 py-1 text-xs border-t">
                {count > 1 && occurrences?.length ? (
                    <>
                        <div className="italic mb-1">
                            This log occurred <b>{count}</b> times:
                        </div>
                        <div className="flex flex-col border rounded bg-surface-primary mb-2 max-h-40 overflow-y-auto">
                            {occurrences.map((ts, i) => {
                                // Show each occurrence's time relative to the recording
                                const offsetFromFirst = ts - firstTimestamp
                                const timeInRecording = item.timeInRecording + offsetFromFirst
                                return (
                                    <div
                                        key={i}
                                        className={clsx(
                                            'flex items-center gap-2 px-2 py-0.5 font-mono',
                                            i > 0 && 'border-t'
                                        )}
                                    >
                                        <span className="text-secondary shrink-0">
                                            {colonDelimitedDuration(timeInRecording / 1000, 2)}
                                        </span>
                                        <span className="truncate">{item.data.content}</span>
                                    </div>
                                )
                            })}
                        </div>
                    </>
                ) : count > 1 ? (
                    <>
                        <div className="italic">
                            This log occurred <b>{count}</b> times in a row.
                        </div>
                        <LemonDivider dashed />
                    </>
                ) : null}
                {item.data.lines?.length && (
                    <CodeSnippet language={Language.JavaScript} wrap thing="console log">
                        {item.data.lines.join(' ')}
                    </CodeSnippet>
                )}

                {item.data.trace?.length ? (
                    <>
                        <LemonDivider dashed />
                        <LemonLabel>Stack trace</LemonLabel>
                        <CodeSnippet language={Language.Markup} wrap thing="stack trace">
                            {item.data.trace.join('\n')}
                        </CodeSnippet>
                    </>
                ) : null}
            </div>
        </div>
    )
}

export function ItemAppState({ item }: ItemAppStateProps): JSX.Element {
    return (
        <div className="w-full font-light" data-attr="item-app-state">
            <div className="px-2 py-1 text-xs cursor-pointer truncate font-mono flex-1">{item.action}</div>
        </div>
    )
}

export function ItemAppStateDetail({ item }: ItemAppStateProps): JSX.Element {
    const stateData = Object.fromEntries(
        Object.entries({
            'prev state': item.stateEvent?.prevState,
            'action payload': item.stateEvent?.payload,
            'next state': item.stateEvent?.nextState,
            'changed state': item.stateEvent?.changedState,
        }).filter(([, value]) => value !== undefined)
    )

    return (
        <div className="w-full font-light" data-attr="item-app-state">
            <div className="px-2 py-1 text-xs border-t flex flex-col gap-2">
                <SimpleKeyValueList item={stateData} header={<strong>{item.action}</strong>} sortItems={false} />
            </div>
        </div>
    )
}
