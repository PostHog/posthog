import clsx from 'clsx'

import { LemonDivider } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { SimpleKeyValueList } from 'lib/components/SimpleKeyValueList'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'

import { InspectorListItemAppState, InspectorListItemConsole } from '../playerInspectorLogic'

export interface ItemConsoleLogProps {
    item: InspectorListItemConsole
}

export interface ItemAppStateProps {
    item: InspectorListItemAppState
}

export function ItemConsoleLog({ item }: ItemConsoleLogProps): JSX.Element {
    return (
        <div className="w-full font-light" data-attr="item-console-log">
            <div className="px-2 py-1 text-xs cursor-pointer truncate font-mono flex-1">{item.data.content}</div>
            {(item.data.count || 1) > 1 ? (
                <span
                    className={clsx(
                        'rounded-lg px-1 mx-2 text-white text-xs font-semibold',
                        item.highlightColor === 'danger' && `bg-fill-error-highlight`,
                        item.highlightColor === 'warning' && `bg-fill-warning-highlight`,
                        item.highlightColor === 'primary' && `bg-fill-success-highlight`
                    )}
                >
                    {item.data.count}
                </span>
            ) : null}
        </div>
    )
}

export function ItemConsoleLogDetail({ item }: ItemConsoleLogProps): JSX.Element {
    return (
        <div className="w-full font-light" data-attr="item-console-log">
            <div className="px-2 py-1 text-xs border-t">
                {(item.data.count || 1) > 1 ? (
                    <>
                        <div className="italic">
                            This log occurred <b>{item.data.count}</b> times in a row.
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
