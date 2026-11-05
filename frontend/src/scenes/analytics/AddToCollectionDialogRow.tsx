import { ItemCheckbox, ItemContent, ItemDescription, ItemTitle } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import { AnalyticsTypeIcon } from './AnalyticsTypeIcon'
import { ANALYTICS_TYPE_INFO, AnalyticsItem } from './analyticsUtils'

/** One pickable item in the add-items dialog: its type, name, and when the person last opened it. */
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
    return (
        <ItemCheckbox
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
                aria-hidden
            >
                <AnalyticsTypeIcon type={item.type} />
            </span>
            <ItemContent variant="menuItem" className="min-w-0">
                <ItemTitle className="truncate">{item.name}</ItemTitle>
                <ItemDescription>
                    {alreadyHere ? (
                        'Already here'
                    ) : item.timestamp ? (
                        <>
                            <span>{info.label} · viewed </span>
                            <TZLabel time={item.timestamp} />
                        </>
                    ) : (
                        info.label
                    )}
                </ItemDescription>
            </ItemContent>
        </ItemCheckbox>
    )
}
