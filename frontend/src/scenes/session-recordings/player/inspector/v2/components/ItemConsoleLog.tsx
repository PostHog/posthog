import { LemonButton } from '@posthog/lemon-ui'
import { SharedListItemConsole } from '../../sharedListLogic'

export interface ItemConsoleLogProps {
    item: SharedListItemConsole
    expanded: boolean
    setExpanded: (expanded: boolean) => void
}

export function ItemConsoleLog({ item, expanded, setExpanded }: ItemConsoleLogProps): JSX.Element {
    return (
        <>
            <LemonButton noPadding onClick={() => setExpanded(!expanded)} status={'primary-alt'} fullWidth>
                <div className="p-2 text-xs cursor-pointer truncate font-mono">{item.data.previewContent}</div>
            </LemonButton>

            {expanded && (
                <div className="p-2 text-xs border-t">
                    <pre className="whitespace-pre-wrap">{item.data.fullContent}</pre>
                </div>
            )}
        </>
    )
}
