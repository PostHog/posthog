import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { SimpleKeyValueList } from 'lib/components/SimpleKeyValueList'

import { InspectorListItemDoctor } from '../playerInspectorLogic'

export interface ItemDoctorProps {
    item: InspectorListItemDoctor
}

export function ItemDoctor({ item }: ItemDoctorProps): JSX.Element {
    return (
        <div data-attr="item-doctor-item" className="w-full font-light">
            <div className="flex-1 cursor-pointer truncate px-2 py-1 font-mono text-xs">{item.tag}</div>
        </div>
    )
}

export function ItemDoctorDetail({ item }: ItemDoctorProps): JSX.Element {
    return (
        <div data-attr="item-doctor-item" className="flex w-full flex-col font-light">
            {['posthog config', 'session options'].includes(item.tag) ? (
                <div className="flex justify-end border-t px-2 py-1 text-xs">
                    <CopyToClipboardInline
                        explicitValue={JSON.stringify(item.data, null, 2)}
                        iconSize="xsmall"
                        iconPosition="end"
                    >
                        Copy to clipboard
                    </CopyToClipboardInline>
                </div>
            ) : null}
            <div className="border-t px-2 py-1 text-xs">{item.data && <SimpleKeyValueList item={item.data} />}</div>
        </div>
    )
}
