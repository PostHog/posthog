import { useLayoutEffect } from 'react'

import { FlatMenuRowKind, visibleFlatMenuRows } from './flatMenuRows'

export const FLAT_MENU_LABEL_ATTRIBUTE = 'data-scene-menu-label'
/** `SceneFlatMenu` hides rows that carry this attribute. Its class list spells the name out, so keep the two equal. */
const COLLAPSED_ROW_ATTRIBUTE = 'data-scene-menu-collapsed'

const ROW_SELECTOR = `[role="separator"], [${FLAT_MENU_LABEL_ATTRIBUTE}], [role^="menuitem"]`

function rowKind(row: Element): FlatMenuRowKind {
    if (row.getAttribute('role') === 'separator') {
        return 'separator'
    }
    return row.hasAttribute(FLAT_MENU_LABEL_ATTRIBUTE) ? 'label' : 'item'
}

function collapseRows(list: HTMLElement): void {
    // The filter unmounts rows that do not match and sets `hidden` on a group once all its rows are gone.
    const rows = Array.from(list.querySelectorAll(ROW_SELECTOR)).filter((row) => !row.closest('[hidden]'))
    const visible = visibleFlatMenuRows(rows.map(rowKind))
    rows.forEach((row, index) => row.toggleAttribute(COLLAPSED_ROW_ATTRIBUTE, !visible[index]))
}

export function useCollapseFlatMenuRows(list: HTMLElement | null): void {
    useLayoutEffect(() => {
        if (!list) {
            return
        }
        collapseRows(list)
        const observer = new MutationObserver(() => collapseRows(list))
        observer.observe(list, { childList: true, subtree: true, attributes: true, attributeFilter: ['hidden'] })
        return () => observer.disconnect()
    }, [list])
}
