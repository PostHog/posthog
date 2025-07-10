import clsx from 'clsx'

import { LemonDivider } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'

import { InspectorListItemConsole } from '../playerInspectorLogic'

export interface ItemConsoleLogProps {
    item: InspectorListItemConsole
}

export function ItemConsoleLog({ item }: ItemConsoleLogProps): JSX.Element {
    return (
        <div className="w-full font-light" data-attr="item-console-log">
            <div className="flex-1 cursor-pointer truncate px-2 py-1 font-mono text-xs">{item.data.content}</div>
            {(item.data.count || 1) > 1 ? (
                <span
                    className={clsx(
                        'mx-2 rounded-lg px-1 text-xs font-semibold text-white',
                        item.highlightColor === 'danger' && `bg-fill-error-highlight`,
                        item.highlightColor === 'warning' && `bg-fill-warning-highlight`,
                        item.highlightColor === 'primary' && `bg-fill-accent-highlight-secondary`
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
            <div className="border-t px-2 py-1 text-xs">
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
