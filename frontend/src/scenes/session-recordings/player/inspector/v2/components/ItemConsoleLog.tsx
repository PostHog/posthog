import clsx from 'clsx'
import { useState } from 'react'
import { SharedListItemConsole } from '../../sharedListLogic'

export interface ItemConsoleLogProps {
    item: SharedListItemConsole
}

export function ItemConsoleLog({ item }: ItemConsoleLogProps): JSX.Element {
    const [expanded, setExpanded] = useState(false)

    return (
        <div className={clsx('rounded bg-light border', expanded && 'border-primary')}>
            <div className="relative cursor-pointer" onClick={() => setExpanded(!expanded)}>
                <div className="flex gap-2 items-start p-2 text-xs cursor-pointer truncate font-mono">
                    {item.data.previewContent}
                </div>
            </div>

            {expanded && (
                <div className="p-2 text-xs border-t">
                    <pre className="whitespace-pre-wrap">{item.data.fullContent}</pre>
                </div>
            )}
        </div>
    )
}
