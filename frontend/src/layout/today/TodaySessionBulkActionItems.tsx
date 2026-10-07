import { useValues } from 'kea'

import { IconArchive, IconFolder, IconPin, IconPinFilled } from '@posthog/icons'

import { TodayMenuParts } from './todayMenuParts'
import { sessionsLabel } from './todaySessionSelection'
import type { TodayBulkAction } from './todaySessionSelectionLogic'
import { TodaySpaceFileList } from './TodaySpaceFileList'
import { todaySpacesLogic } from './todaySpacesLogic'

/** The sidebar's selection, or one space feed's. Both offer the same bulk changes. */
export interface TodayBulkSelection {
    /** The space every selected session sits in, or `null` when the selection spans spaces. */
    spaceId: string | null
    selectedSessionIds: string[]
    bulkPinDirection: 'pin' | 'unpin'
    bulkAction: TodayBulkAction | null
    runningSelectedCount: number
    pinSelected: () => void
    fileSelectedTo: (spaceId: string) => void
    requestBulkArchive: () => void
}

/** What the selection bar offers, as menu items, so a right-click on a selected row acts on the whole selection. */
export function TodaySessionBulkActionItems({
    parts: { Item, Separator, Sub },
    selection: {
        spaceId,
        selectedSessionIds,
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
    const { spaces } = useValues(todaySpacesLogic)
    const sessions = sessionsLabel(selectedSessionIds.length)
    const pin = bulkPinDirection === 'pin'
    // One bulk change at a time, like the selection bar. "File to…" hides, because a submenu can't be disabled here.
    const busy = bulkAction !== null
    // Filing needs a space other than the one the sessions already sit in.
    const canFile = spaces.length > (spaceId ? 1 : 0)
    const attr = (name: string): string => `${dataAttrPrefix}-${name}`

    return (
        <>
            <Item onClick={pinSelected} disabled={busy} dataAttr={attr('pin')}>
                {pin ? <IconPin /> : <IconPinFilled />}
                {`${pin ? 'Pin' : 'Unpin'} ${sessions}`}
            </Item>
            {canFile && !busy && (
                <Sub
                    label={
                        <>
                            <IconFolder />
                            {`File ${sessions} to…`}
                        </>
                    }
                    title={`File ${sessions} to…`}
                    dataAttr={attr('file')}
                >
                    <TodaySpaceFileList
                        currentSpaceId={spaceId}
                        onSelect={fileSelectedTo}
                        itemDataAttr={attr('file-space')}
                        searchDataAttr={attr('file-search')}
                    />
                </Sub>
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
