import { useLayoutEffect } from 'react'

import { MenuRowKind, visibleMenuRows } from './menuRowVisibility'

export const MENU_LABEL_ATTRIBUTE = 'data-scene-menu-label'
/** Tailwind reads class names from source text, so the class below spells this name out. Keep the two equal. */
const COLLAPSED_ROW_ATTRIBUTE = 'data-scene-menu-collapsed'
export const COLLAPSED_ROWS_HIDDEN_CLASS = '[&_[data-scene-menu-collapsed]]:hidden'

const ROW_SELECTOR = `[role="separator"], [${MENU_LABEL_ATTRIBUTE}], [role^="menuitem"]`

function rowKind(row: Element): MenuRowKind {
    if (row.getAttribute('role') === 'separator') {
        return 'separator'
    }
    return row.hasAttribute(MENU_LABEL_ATTRIBUTE) ? 'label' : 'item'
}

function collapseRows(container: HTMLElement): void {
    // The filter unmounts rows that do not match and sets `hidden` on a group once all its rows are gone.
    const rows = Array.from(container.querySelectorAll(ROW_SELECTOR)).filter((row) => !row.closest('[hidden]'))
    const visible = visibleMenuRows(rows.map(rowKind))
    rows.forEach((row, index) => row.toggleAttribute(COLLAPSED_ROW_ATTRIBUTE, !visible[index]))
}

export function useCollapseMenuRows(container: HTMLElement | null): void {
    useLayoutEffect(() => {
        if (!container) {
            return
        }
        collapseRows(container)
        const observer = new MutationObserver(() => collapseRows(container))
        observer.observe(container, { childList: true, subtree: true, attributes: true, attributeFilter: ['hidden'] })
        return () => observer.disconnect()
    }, [container])
}
