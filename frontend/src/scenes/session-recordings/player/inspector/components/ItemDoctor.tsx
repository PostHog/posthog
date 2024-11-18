import { SimpleKeyValueList } from 'scenes/session-recordings/player/inspector/components/SimpleKeyValueList'

import { InspectorListItemDoctor } from '../playerInspectorLogic'

export interface ItemDoctorProps {
    item: InspectorListItemDoctor
    expanded: boolean
}

export function ItemDoctor({ item, expanded }: ItemDoctorProps): JSX.Element {
    return (
        <div data-attr="item-doctor-item" className="font-normal w-full">
            <div className="px-2 py-1 text-xs cursor-pointer truncate font-mono flex-1">{item.tag}</div>

            {expanded && (
                <div className="px-2 py-1 text-xs border-t">{item.data && <SimpleKeyValueList item={item.data} />}</div>
            )}
        </div>
    )
}
