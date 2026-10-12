import { IconArchive, IconPin, IconPinFilled } from '@posthog/icons'

import { TodayMenuParts } from './todayMenuParts'
import { sessionsLabel } from './todaySessionSelection'
import type { TodayBulkAction } from './todaySessionSelectionLogic'

/** The sidebar's selection, or one space feed's. Both offer the same bulk changes. */
export interface TodayBulkSelection {
    selectedSessionIds: string[]
    bulkPinDirection: 'pin' | 'unpin'
    bulkAction: TodayBulkAction | null
    runningSelectedCount: number
    pinSelected: () => void
    requestBulkArchive: () => void
}

/** What the selection bar offers, as menu items, so a right-click on a selected row acts on the whole selection. */
export function TodaySessionBulkActionItems({
    parts: { Item, Separator },
    selection: {
        selectedSessionIds,
        bulkPinDirection,
        bulkAction,
        runningSelectedCount,
        pinSelected,
        requestBulkArchive,
    },
    dataAttrPrefix,
}: {
    parts: TodayMenuParts
    selection: TodayBulkSelection
    /** Starts each item's `data-attr`, so every surface counts on its own. */
    dataAttrPrefix: string
}): JSX.Element {
    const sessions = sessionsLabel(selectedSessionIds.length)
    const pin = bulkPinDirection === 'pin'
    // One bulk change at a time, like the selection bar.
    const busy = bulkAction !== null
    const attr = (name: string): string => `${dataAttrPrefix}-${name}`

    return (
        <>
            <Item onClick={pinSelected} disabled={busy} dataAttr={attr('pin')}>
                {pin ? <IconPin /> : <IconPinFilled />}
                {`${pin ? 'Pin' : 'Unpin'} ${sessions}`}
            </Item>
            <Separator />
            <Item onClick={requestBulkArchive} disabled={busy} dataAttr={attr('archive')}>
                <IconArchive />
                {/* Only a selection with a running session asks first, so only then does the label promise a next step. */}
                {`Archive ${sessions}${runningSelectedCount > 0 ? '…' : ''}`}
            </Item>
        </>
    )
}
