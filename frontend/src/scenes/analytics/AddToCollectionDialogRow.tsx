import { ItemCheckbox, ItemContent, ItemTitle, Text } from '@posthog/quill'

import { AnalyticsTypeIcon } from './AnalyticsTypeIcon'
import { ANALYTICS_TYPE_INFO, AnalyticsItem } from './analyticsUtils'

/** One pickable item in the add-items dialog, with the collection it sits in now. */
export function AddToCollectionDialogRow({
    item,
    checked,
    alreadyHere,
    onToggle,
}: {
    item: AnalyticsItem
    checked: boolean
    alreadyHere: boolean
    onToggle: (item: AnalyticsItem) => void
}): JSX.Element {
    const info = ANALYTICS_TYPE_INFO[item.type]
    const where = alreadyHere ? 'Already here' : item.spaceName ? `In ${item.spaceName}` : null
    return (
        <ItemCheckbox
            size="xs"
            aria-checked={checked || alreadyHere}
            disabled={alreadyHere}
            onClick={() => onToggle(item)}
            className="w-full disabled:opacity-50"
            data-attr="analytics-add-items-row"
        >
            <span
                className="flex size-4 shrink-0 items-center justify-center [&_svg]:size-4"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ color: info.color }}
                aria-label={info.label}
            >
                <AnalyticsTypeIcon type={item.type} />
            </span>
            <ItemContent variant="menuItem" className="min-w-0 flex-1">
                <ItemTitle className="truncate">{item.name}</ItemTitle>
            </ItemContent>
            {where && (
                <Text size="xs" variant="muted" className="max-w-40 shrink-0 truncate">
                    {where}
                </Text>
            )}
        </ItemCheckbox>
    )
}
