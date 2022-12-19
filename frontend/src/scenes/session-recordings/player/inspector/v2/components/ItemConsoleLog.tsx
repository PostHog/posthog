import { SharedListItemConsole } from '../../sharedListLogic'

export interface ItemConsoleLogProps {
    item: SharedListItemConsole
    expanded: boolean
    setExpanded: (expanded: boolean) => void
}

export function ItemConsoleLog({ item, expanded, setExpanded }: ItemConsoleLogProps): JSX.Element {
    return (
        <>
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
        </>
    )
}
