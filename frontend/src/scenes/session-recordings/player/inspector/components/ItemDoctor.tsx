import { LemonButton } from '@posthog/lemon-ui'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { InspectorListItemDoctor } from '../playerInspectorLogic'

export interface ItemDoctorProps {
    item: InspectorListItemDoctor
    expanded: boolean
    setExpanded: (expanded: boolean) => void
}

export function ItemDoctor({ item, expanded, setExpanded }: ItemDoctorProps): JSX.Element {
    return (
        <>
            <LemonButton
                noPadding
                onClick={() => setExpanded(!expanded)}
                fullWidth
                data-attr="item-doctor-item"
                className="font-normal"
            >
                <div className="p-2 text-xs cursor-pointer truncate font-mono flex-1">{item.tag}</div>
            </LemonButton>

            {expanded && (
                <div className="p-2 text-xs border-t">
                    {item.data && (
                        <CodeSnippet language={Language.JSON} wrap thing={`custom event - ${item.tag}`}>
                            {JSON.stringify(item.data, null, 2)}
                        </CodeSnippet>
                    )}
                </div>
            )}
        </>
    )
}
