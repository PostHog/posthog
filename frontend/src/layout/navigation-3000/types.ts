import { Logic, LogicWrapper } from 'kea'
import { Dayjs } from 'lib/dayjs'
import { LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import React from 'react'

export interface SidebarLogic extends Logic {
    actions: Record<never, never> // No actions required in the base version
    values: {
        isLoading: boolean
        contents: Accordion[] | BasicListItem[] | ExtendedListItem[]
        /**
         * Tuple for an item inside an accordion, the first element being the accordion key.
         * Otherwise a primitive (string or number key). Null if no item is active.
         */
        activeListItemKey: string | number | [string, string | number] | null
    }
    selectors: {
        isLoading: (state: any, props?: any) => SidebarLogic['values']['isLoading']
        contents: (state: any, props?: any) => SidebarLogic['values']['contents']
        activeListItemKey: (state: any, props?: any) => SidebarLogic['values']['activeListItemKey']
    }
}

interface NavbarItemBase {
    identifier: string
    label: string
    icon: JSX.Element
}
export interface SceneNavbarItem extends NavbarItemBase {
    pointer: string
}
export interface SidebarNavbarItem extends NavbarItemBase {
    pointer: LogicWrapper<SidebarLogic>
}
/** A navbar item either points to a sidebar (via a sidebar logic) or directly to a scene (via a URL). */
// TODO: Remove NavbarItemBase from NavbarItem once all 3000 navbar items are interactive
export type NavbarItem = NavbarItemBase | SceneNavbarItem | SidebarNavbarItem

export interface Accordion {
    key: string
    title: string
    items: BasicListItem[] | ExtendedListItem[]
    loadMore?: () => void
    loading?: boolean
}

export interface SearchMatch {
    /**
     * Fields that are matching the search term - they will be shown within the list item.
     * Not included in server-side search.
     */
    matchingFields?: readonly string[]
    /** What parts of the name were matched - they will be bolded. */
    nameHighlightRanges?: readonly [number, number][]
}

export interface BasicListItem {
    /**
     * Key uniquely identifying this item.
     *
     * This can also be an array of keys - for example persons have multiple distinct IDs.
     * Note that in such an array, EACH key must represent this and ONLY this item.
     */
    key: string | number | string[]
    /** Item name. This must be a string for accesibility. */
    name: string
    /** Whether the name is a placeholder (e.g. an insight derived name), in which case it'll be italicized. */
    isNamePlaceholder?: boolean
    /**
     * URL within the app.
     * In rare cases this can be explicitly null (e.g. the "Load more" item). Such items are italicized.
     */
    url: string | null
    /** An optional marker to highlight item state. */
    marker?: {
        /** A marker of type `fold` is a small triangle in the top left, `ribbon` is a narrow ribbon to the left. */
        type: 'fold' | 'ribbon'
        /**
         * Optional marker color.
         * @default 'muted'
         */
        status?: 'muted' | 'success' | 'warning' | 'danger'
    }
    /** If search is on, this should be present to convey why this item is included in results. */
    searchMatch?: SearchMatch | null
    menuItems?: LemonMenuItems | ((initiateRename?: () => void) => LemonMenuItems)
    onRename?: (newName: string) => Promise<void>
    /** Ref to the corresponding <a> element. This is injected automatically when the element is rendered. */
    ref?: React.MutableRefObject<HTMLElement | null>
}

export type ExtraListItemContext = string | Dayjs
export interface ExtendedListItem extends BasicListItem {
    summary: string | JSX.Element
    /** A small piece of extra context to be displayed in the top right of the row. */
    extraContextTop: ExtraListItemContext
    /** A small piece of extra context to be displayed in the bottom right of the row. */
    extraContextBottom: ExtraListItemContext
}
