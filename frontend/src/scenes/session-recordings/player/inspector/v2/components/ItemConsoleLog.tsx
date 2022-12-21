import { LemonButton } from '@posthog/lemon-ui'
import { InspectorListItemConsole } from '../../playerInspectorLogic'

export interface ItemConsoleLogProps {
    item: InspectorListItemConsole
    expanded: boolean
    setExpanded: (expanded: boolean) => void
}

export function ItemConsoleLog({ item, expanded, setExpanded }: ItemConsoleLogProps): JSX.Element {
    return (
        <>
            <LemonButton noPadding onClick={() => setExpanded(!expanded)} status={'primary-alt'} fullWidth>
                <div className="p-2 text-xs cursor-pointer truncate font-mono">{item.data.content}</div>
            </LemonButton>

            {expanded && (
                <div className="p-2 text-xs border-t">
                    <pre className="whitespace-pre-wrap">{item.data.content}</pre>
                </div>
            )}
        </>
    )
}
