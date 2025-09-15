import { Logic, LogicWrapper } from 'kea'
import React from 'react'

import { LemonTagType, SideAction } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { Dayjs } from 'lib/dayjs'
import { LemonMenuItems } from 'lib/lemon-ui/LemonMenu'

export interface SidebarLogic extends Logic {
    actions: Record<never, never> // No actions required in the base version
    values: {
        contents: SidebarCategory[]
        /**
         * Tuple for an item inside an accordion, the first element being the accordion key.
         * Otherwise a primitive (string or number key). Null if no item is active.
         */
        activeListItemKey?: string | number | [string, string | number] | null
        /** If this selector returns true, the searchTerm value will be debounced. */
        debounceSearch?: boolean
    }
    selectors: {
        contents: (state: any, props?: any) => SidebarLogic['values']['contents']
        activeListItemKey?: (state: any, props?: any) => SidebarLogic['values']['activeListItemKey']
        debounceSearch?: (state: any, props?: any) => SidebarLogic['values']['debounceSearch']
    }
}

interface NavbarItemBase {
    identifier: string
    label: string
    icon: JSX.Element
    featureFlag?: (typeof FEATURE_FLAGS)[keyof typeof FEATURE_FLAGS]
    tag?: 'alpha' | 'beta' | 'new'
    sideAction?: Omit<SideAction, 'divider' | 'data-attr' | 'tooltipPlacement'> & { identifier: string }
    tooltipDocLink?: string
    /** @deprecated */
    onClick?: () => void
}
export interface SceneNavbarItem extends NavbarItemBase {
    to: string
    logic?: undefined
}
export interface SidebarNavbarItem extends NavbarItemBase {
    to?: undefined
    logic: LogicWrapper<SidebarLogic>
}
/** A navbar item either points to a sidebar (via a sidebar logic) or directly to a scene (via a URL). */
export type NavbarItem = NavbarItemBase | SceneNavbarItem | SidebarNavbarItem

export type ListItemSaveHandler = (newName: string) => Promise<void>

export interface SidebarCategoryBase {
    key: string
    /** Category content noun. If the plural form is non-standard, provide a tuple with both forms. @example 'person' */
    noun: string | [singular: string, plural: string]
    items: BasicListItem[] | ExtendedListItem[] | ListItemAccordion[]
    icon?: JSX.Element
    /** Ref to the corresponding <a> element. This is injected automatically when the element is rendered. */
    ref?: React.MutableRefObject<HTMLElement | null>
}

export interface ListItemAccordion extends SidebarCategoryBase {
    depth?: number
}

/** A category of items. This is either displayed directly for sidebars with only one category, or as an accordion. */
export interface SidebarCategory extends SidebarCategoryBase {
    loading: boolean
    /**
     * Items can be created in three ways:
     * 1. In a "new item" scene, in which case this is a string pointing to the scene URL (such as new insight).
     * 2. In a modal, in which case this is a zero-argument function that opens the modal.
     * 3. Directly in the sidebar, in which case this is a single-argument function that takes the new item's name
     *    and saves it. For a smooth experience, this should only resolve once the new item is present in `contents`.
     */
    onAdd?: string | (() => void) | ListItemSaveHandler
    /**
     * Name validation. Returns a message string in case of an error, otherwise null.
     * This is relevant if the category has `onAdd` or items have `onRename`.
     */
    validateName?: (name: string) => string | null
    /** Optional extra JSX rendered in the background, enabling category-specific modals. */
    modalContent?: JSX.Element
    /** Controls for data that's only loaded partially from the API at first. This powers infinite loading. */
    remote?: {
        isItemLoaded: (index: number) => boolean
        loadMoreItems: (startIndex: number, stopIndex: number) => Promise<void>
        itemCount: number
        /** The "page" size. @default 100 */
        minimumBatchSize?: number
    }

    /** Optional component to render when the category is empty. */
    emptyComponent?: JSX.Element
    /** Optional function to determine whether the empty component should be shown */
    emptyComponentLogic?: (items: BasicListItem[] | ExtendedListItem[] | ListItemAccordion[]) => boolean
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

/** Single-row list item. */
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
     * URL within the app. In specific cases this can be null - such items are italicized.
     */
    url: string | null
    onClick?: () => void
    /** An optional marker to highlight item state. */
    marker?: {
        /** A marker of type `fold` is a small triangle in the top left, `ribbon` is a narrow ribbon to the left. */
        type: 'fold' | 'ribbon'
        /**
         * Optional marker color.
         * @default 'muted'
         */
        status?: 'muted' | 'success' | 'warning' | 'danger' | 'completion'
    }
    /** An optional tag shown as a suffix of the name. */
    tag?: {
        status: LemonTagType
        text: string
    }
    /** If search is on, this should be present to convey why this item is included in results. */
    searchMatch?: SearchMatch | null
    menuItems?: LemonMenuItems | ((initiateRename?: () => void) => LemonMenuItems)
    onRename?: ListItemSaveHandler
    /** Ref to the corresponding <a> element. This is injected automatically when the element is rendered. */
    ref?: React.MutableRefObject<HTMLElement | null>
    /** If this item is inside an accordion, this is the depth of the accordion. */
    depth?: number
    /** Element to render at the end of the row */
    endElement?: string | JSX.Element
}

export type ExtraListItemContext = string | Dayjs
/** Double-row list item. */
export interface ExtendedListItem extends BasicListItem {
    summary: string | JSX.Element
    /** A small piece of extra context to be displayed in the top right of the row. */
    extraContextTop: ExtraListItemContext
    /** A small piece of extra context to be displayed in the bottom right of the row. */
    extraContextBottom: ExtraListItemContext
}

/** Just a stub for a list item that's being added. */
export interface TentativeListItem {
    key: '__tentative__'
    onSave: ListItemSaveHandler
    onCancel: () => void
    loading: boolean
    adding: boolean
    ref?: BasicListItem['ref']
}

export interface ButtonListItem extends BasicListItem {
    key: '__button__'
    onClick: () => void
    icon?: JSX.Element
}
