import { useValues } from 'kea'

import { IconArchive, IconLock, IconPin, IconPinFilled } from '@posthog/icons'

import { TodayMenuParts } from './todayMenuParts'
import { sessionsLabel } from './todaySessionSelection'
import type { TodayBulkAction } from './todaySessionSelectionLogic'
import { todaySpacesLogic } from './todaySpacesLogic'

/** The sidebar's selection, or one space feed's. Both offer the same bulk changes. */
export interface TodayBulkSelection {
    /** The space every selected session sits in, or `null` when the selection spans spaces. */
    spaceId: string | null
    selectedSessionIds: string[]
    ownsAllSelected: boolean
    bulkPinDirection: 'pin' | 'unpin'
    bulkAction: TodayBulkAction | null
    runningSelectedCount: number
    pinSelected: () => void
    fileSelectedTo: (spaceId: string) => void
    requestBulkArchive: () => void
}

/** What the selection bar offers, as menu items, so a right-click on a selected row acts on the whole selection. */
export function TodaySessionBulkActionItems({
    parts: { Item, Separator },
    selection: {
        spaceId,
        selectedSessionIds,
        ownsAllSelected,
        bulkPinDirection,
        bulkAction,
        runningSelectedCount,
        pinSelected,
        fileSelectedTo,
        requestBulkArchive,
    },
    dataAttrPrefix,
}: {
    parts: TodayMenuParts
    selection: TodayBulkSelection
    /** Starts each item's `data-attr`, so every surface counts on its own. */
    dataAttrPrefix: string
}): JSX.Element {
    const { personalSpaceId } = useValues(todaySpacesLogic)
    const sessions = sessionsLabel(selectedSessionIds.length)
    const pin = bulkPinDirection === 'pin'
    const busy = bulkAction !== null
    const attr = (name: string): string => `${dataAttrPrefix}-${name}`

    return (
        <>
            <Item onClick={pinSelected} disabled={busy} dataAttr={attr('pin')}>
                {pin ? <IconPin /> : <IconPinFilled />}
                {`${pin ? 'Pin' : 'Unpin'} ${sessions}`}
            </Item>
            {ownsAllSelected && personalSpaceId && spaceId !== personalSpaceId && (
                <Item
                    onClick={() => fileSelectedTo(personalSpaceId)}
                    disabled={busy}
                    dataAttr={attr('move-to-personal')}
                >
                    <IconLock />
                    {`Move ${sessions} to personal`}
                </Item>
            )}
            <Separator />
            <Item onClick={requestBulkArchive} disabled={busy} dataAttr={attr('archive')}>
                <IconArchive />
                {/* Only a selection with a running session asks first, so only then does the label promise a next step. */}
                {`Archive ${sessions}${runningSelectedCount > 0 ? '…' : ''}`}
            </Item>
        </>
    )
}
