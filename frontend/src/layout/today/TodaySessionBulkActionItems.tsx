import { useActions, useValues } from 'kea'

import { IconArchive, IconFolder, IconPin, IconPinFilled } from '@posthog/icons'

import { TodayMenuParts } from './todayMenuParts'
import { sessionsLabel } from './todaySessionSelection'
import { todaySessionSelectionLogic } from './todaySessionSelectionLogic'
import { TodaySpaceFileList } from './TodaySpaceFileList'
import { todaySpacesLogic } from './todaySpacesLogic'

/** What the selection bar offers, as menu items, so a right-click on a selected row acts on the whole selection. */
export function TodaySessionBulkActionItems({
    parts: { Item, Separator, Sub },
    dataAttrPrefix,
}: {
    parts: TodayMenuParts
    /** Starts each item's `data-attr`, so every surface counts on its own. */
    dataAttrPrefix: string
}): JSX.Element {
    const { selectedSessionIds, bulkPinDirection, bulkAction, runningSelectedCount } =
        useValues(todaySessionSelectionLogic)
    const { pinSelected, fileSelectedTo, requestBulkArchive } = useActions(todaySessionSelectionLogic)
    const { spaces } = useValues(todaySpacesLogic)
    const sessions = sessionsLabel(selectedSessionIds.length)
    const pin = bulkPinDirection === 'pin'
    // One bulk change at a time, like the selection bar. "File to…" hides, because a submenu can't be disabled here.
    const busy = bulkAction !== null
    const attr = (name: string): string => `${dataAttrPrefix}-${name}`

    return (
        <>
            <Item onClick={pinSelected} disabled={busy} dataAttr={attr('pin')}>
                {pin ? <IconPin /> : <IconPinFilled />}
                {`${pin ? 'Pin' : 'Unpin'} ${sessions}`}
            </Item>
            {spaces.length > 0 && !busy && (
                <Sub
                    label={
                        <>
                            <IconFolder />
                            {`File ${sessions} to…`}
                        </>
                    }
                    dataAttr={attr('file')}
                >
                    <TodaySpaceFileList
                        currentSpaceId={null}
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
