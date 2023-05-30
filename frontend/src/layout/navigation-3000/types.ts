import { Logic, LogicWrapper } from 'kea'
import { Dayjs } from 'lib/dayjs'
import { LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import React from 'react'

export interface SidebarLogic extends Logic {
    actions: Record<never, never> // No actions required in the base version
    values: {
        isLoading: boolean
        contents: Accordion[] | BasicListItem[] | ExtendedListItem[]
        activeListItemKey: BasicListItem['key'] | null
    }
    selectors: {
        isLoading: (state: any, props?: any) => boolean
        contents: (state: any, props?: any) => Accordion[] | BasicListItem[] | ExtendedListItem[]
        activeListItemKey: (state: any, props?: any) => BasicListItem['key'] | null
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
}

export interface BasicListItem {
    key: string | number
    /** Item name. This must be a string for accesibility. */
    name: string
    /** URL within the app. */
    url: string
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
    searchMatch?: {
        /** Fields that are matching the search term - they will be shown within the list item. */
        matchingFields: readonly string[]
        /** What parts of the name were matched - they will be bolded. */
        nameHighlightRanges?: readonly [number, number][]
    } | null

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
