import { IconCopy } from '@posthog/icons'
import { LemonMenuItem, lemonToast } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import {
    BulkSerializeOptions,
    InspectorSerializeFormat,
    serializeInspectorItem,
    serializeInspectorItems,
} from './inspectorItemSerializers'
import { InspectorListItem } from './playerInspectorLogic'

const PER_ITEM_DESCRIPTION = 'log entry'
const BULK_DESCRIPTION = 'inspector logs'

export function inspectorItemCopyMenuItems(item: InspectorListItem): LemonMenuItem[] {
    return [
        {
            label: 'Copy as text',
            icon: <IconCopy />,
            onClick: () => void copyToClipboard(serializeInspectorItem(item, 'text'), PER_ITEM_DESCRIPTION),
            'data-attr': 'player-inspector-row-copy-text',
        },
        {
            label: 'Copy as JSON',
            icon: <IconCopy />,
            onClick: () => void copyToClipboard(serializeInspectorItem(item, 'json'), PER_ITEM_DESCRIPTION),
            'data-attr': 'player-inspector-row-copy-json',
        },
    ]
}

export function bulkCopyInspectorItems(
    items: InspectorListItem[],
    format: InspectorSerializeFormat,
    opts: BulkSerializeOptions = {}
): void {
    const { output, truncated, itemCount } = serializeInspectorItems(items, format, opts)
    void copyToClipboard(output, BULK_DESCRIPTION)
    if (truncated) {
        lemonToast.warning(
            `Copied the first ${itemCount.toLocaleString()} items — the recording has more. Narrow your filters to capture the rest.`
        )
    }
}
