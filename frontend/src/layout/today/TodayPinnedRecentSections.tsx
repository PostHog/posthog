import { Fragment } from 'react'

import { HrefPin } from './sidebar/hrefPins'
import { SidebarRowEnter } from './sidebar/SidebarRowEnter'
import { SidebarSection } from './sidebar/SidebarSection'
import { SortableSidebarList } from './sidebar/SortableSidebarList'

export type TodayPinnedRecentSection = 'pinned' | 'recents'

function sectionRows<T>(
    items: T[],
    valueOf: (item: T) => string,
    render: (item: T) => JSX.Element,
    onMove?: (item: T, overItem: T) => void
): JSX.Element | JSX.Element[] {
    if (!onMove || items.length < 2) {
        return items.map((item) => <Fragment key={valueOf(item)}>{render(item)}</Fragment>)
    }
    return (
        <SortableSidebarList
            rows={items.map((item) => ({ value: valueOf(item), item }))}
            renderRow={(row) => render(row.item)}
            onReorder={(fromIndex, toIndex) => onMove(items[fromIndex], items[toIndex])}
        />
    )
}

export function TodayPinnedRecentSections<P extends HrefPin<string>, R extends { href: string }>({
    pins,
    recents,
    renderPin,
    renderRecent,
    onMovePin,
    onMoveRecent,
    isSectionOpen,
    onToggleSection,
    dataAttrPrefix,
}: {
    pins: P[]
    recents: R[]
    renderPin: (pin: P) => JSX.Element
    renderRecent: (recent: R) => JSX.Element
    /** Lets a person drag pins into a new order. Leave it out while a search hides rows. */
    onMovePin?: (pin: P, overPin: P) => void
    /** Lets a person drag recents into a new order. Leave it out while a search hides rows. */
    onMoveRecent?: (recent: R, overRecent: R) => void
    isSectionOpen: (section: TodayPinnedRecentSection) => boolean
    onToggleSection: (section: TodayPinnedRecentSection) => void
    dataAttrPrefix: string
}): JSX.Element {
    return (
        <>
            {pins.length > 0 && (
                <SidebarSection
                    label="Pinned"
                    open={isSectionOpen('pinned')}
                    count={pins.length}
                    showCount={false}
                    onToggle={() => onToggleSection('pinned')}
                    divider
                    dataAttr={`${dataAttrPrefix}-section-pinned`}
                >
                    {sectionRows(
                        pins,
                        (pin) => pin.key,
                        (pin) => (
                            <SidebarRowEnter pinKey={pin.key}>{renderPin(pin)}</SidebarRowEnter>
                        ),
                        onMovePin
                    )}
                </SidebarSection>
            )}
            {recents.length > 0 && (
                <SidebarSection
                    label="Recents"
                    open={isSectionOpen('recents')}
                    count={recents.length}
                    showCount={false}
                    onToggle={() => onToggleSection('recents')}
                    divider
                    dataAttr={`${dataAttrPrefix}-section-recents`}
                >
                    {sectionRows(recents, (recent) => recent.href, renderRecent, onMoveRecent)}
                </SidebarSection>
            )}
        </>
    )
}
