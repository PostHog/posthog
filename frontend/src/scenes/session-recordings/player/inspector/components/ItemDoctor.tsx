import { LemonButton } from '@posthog/lemon-ui'
import { SimpleKeyValueList } from 'scenes/session-recordings/player/inspector/components/SimpleKeyValueList'

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
                <div className="p-2 text-xs border-t">{item.data && <SimpleKeyValueList item={item.data} />}</div>
            )}
        </>
    )
}
