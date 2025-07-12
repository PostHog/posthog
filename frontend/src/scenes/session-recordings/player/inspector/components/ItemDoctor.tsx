import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { SimpleKeyValueList } from 'lib/components/SimpleKeyValueList'

import { InspectorListItemDoctor } from '../playerInspectorLogic'

export interface ItemDoctorProps {
    item: InspectorListItemDoctor
}

export function ItemDoctor({ item }: ItemDoctorProps): JSX.Element {
    return (
        <div data-attr="item-doctor-item" className="font-light w-full">
            <div className="px-2 py-1 text-xs cursor-pointer truncate font-mono flex-1">{item.tag}</div>
        </div>
    )
}

export function ItemDoctorDetail({ item }: ItemDoctorProps): JSX.Element {
    return (
        <div data-attr="item-doctor-item" className="font-light w-full flex flex-col">
            {['posthog config', 'session options'].includes(item.tag) ? (
                <div className="px-2 py-1 text-xs border-t flex justify-end">
                    <CopyToClipboardInline
                        explicitValue={JSON.stringify(item.data, null, 2)}
                        iconSize="xsmall"
                        iconPosition="end"
                    >
                        Copy to clipboard
                    </CopyToClipboardInline>
                </div>
            ) : null}
            <div className="px-2 py-1 text-xs border-t">{item.data && <SimpleKeyValueList item={item.data} />}</div>
        </div>
    )
}
