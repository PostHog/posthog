import type * as React from 'react'

interface ActionMenuItemBase {
    id: string
    label: string
    icon?: React.ReactNode
    /** Extra words the search matches on, such as a synonym the label leaves out. */
    keywords?: string[]
    /** Rows with different sections get a separator between them. */
    section?: string
    disabledReason?: string
    tooltip?: string
    dataAttr?: string
}

export interface ActionMenuAction extends ActionMenuItemBase {
    type?: 'action'
    onSelect: () => void
    destructive?: boolean
    shortcut?: React.ReactNode
    /** Appends "…" to the label, for a row that opens a dialog, popover or panel. */
    opensFloatingUi?: boolean
}

export interface ActionMenuCheckbox extends ActionMenuItemBase {
    type: 'checkbox'
    checked: boolean
    onCheckedChange: (checked: boolean) => void
}

export interface ActionMenuRadioOption {
    value: string
    label: string
    icon?: React.ReactNode
    disabledReason?: string
}

export interface ActionMenuRadio extends ActionMenuItemBase {
    type: 'radio'
    value: string
    options: ActionMenuRadioOption[]
    onValueChange: (value: string) => void
}

export interface ActionMenuSubmenu extends ActionMenuItemBase {
    type: 'submenu'
    items: ActionMenuItem[]
    /**
     * Inside a top-level submenu, a submenu renders as a labeled group of rows by default, so the menu nests one level.
     * `submenu` keeps a real submenu, for a long list of toggles or a submenu that holds another submenu.
     */
    display?: 'group' | 'submenu'
    /** False keeps the rows out of the search, which then lists the submenu as one row that opens it. */
    searchable?: boolean
    onOpenChange?: (open: boolean) => void
}

/** A row that closes the menu and opens rich content (inputs, comboboxes) in a popover anchored to the trigger. */
export interface ActionMenuPanel extends ActionMenuItemBase {
    type: 'panel'
    render: () => React.ReactNode
    panelClassName?: string
}

export type ActionMenuItem =
    | ActionMenuAction
    | ActionMenuCheckbox
    | ActionMenuRadio
    | ActionMenuSubmenu
    | ActionMenuPanel

export function isDestructive(item: ActionMenuItem): item is ActionMenuAction {
    return (item.type === undefined || item.type === 'action') && !!item.destructive
}

/** Whether a submenu, with its hoisted destructive rows taken out, still has a row to show. */
export function hasRows(item: ActionMenuItem, hoisting: boolean): boolean {
    if (item.type !== 'submenu') {
        return !(hoisting && isDestructive(item))
    }
    const keepsDestructive = !hoisting || item.display === 'submenu'
    return item.items.some((child) => hasRows(child, !keepsDestructive))
}

/** Destructive rows from anywhere outside a kept submenu, in declared order. The menu lists them last. */
export function collectDestructive(items: ActionMenuItem[], topLevel = true): ActionMenuAction[] {
    return items.flatMap((item) => {
        if (isDestructive(item)) {
            return [item]
        }
        if (item.type === 'submenu' && (topLevel || item.display !== 'submenu')) {
            return collectDestructive(item.items, false)
        }
        return []
    })
}

export type ActionMenuSearchResult =
    | { kind: 'item'; item: Exclude<ActionMenuItem, ActionMenuRadio>; path: string[] }
    | { kind: 'radio-option'; radio: ActionMenuRadio; option: ActionMenuRadioOption; path: string[] }

function normalize(text: string): string {
    return text
        .normalize('NFD')
        .replace(/[̀-ͯ]/g, '')
        .toLowerCase()
}

function matches(query: string[], words: (string | undefined)[]): boolean {
    const haystack = normalize(words.filter(Boolean).join(' '))
    return query.every((token) => haystack.includes(token))
}

/**
 * One flat list of the rows that match the query, from every level. A submenu whose own label matches comes first,
 * as a row that opens it, then its rows. Each result carries its path so a row can say where it lives. Destructive
 * rows go last.
 */
export function searchActionMenu(items: ActionMenuItem[], query: string): ActionMenuSearchResult[] {
    const tokens = normalize(query).split(/\s+/).filter(Boolean)
    if (tokens.length === 0) {
        return []
    }
    const results: ActionMenuSearchResult[] = []
    const destructive: ActionMenuSearchResult[] = []
    const walk = (level: ActionMenuItem[], path: string[]): void => {
        for (const item of level) {
            const words = [...path, item.label, ...(item.keywords ?? [])]
            if (item.type === 'submenu') {
                if (!hasRows(item, false)) {
                    continue
                }
                if (path.length > 0 && matches(tokens, words)) {
                    results.push({ kind: 'item', item, path })
                }
                if (item.searchable !== false) {
                    walk(item.items, [...path, item.label])
                }
            } else if (item.type === 'radio') {
                for (const option of item.options) {
                    if (matches(tokens, [...words, option.label])) {
                        results.push({ kind: 'radio-option', radio: item, option, path: [...path, item.label] })
                    }
                }
            } else if (matches(tokens, words)) {
                ;(isDestructive(item) ? destructive : results).push({ kind: 'item', item, path })
            }
        }
    }
    walk(items, [])
    return [...results, ...destructive]
}
