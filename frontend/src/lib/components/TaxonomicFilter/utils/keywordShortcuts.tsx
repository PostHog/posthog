import { IconCursor } from '@posthog/icons'

import {
    QuickFilterItem,
    TaxonomicFilterGroup,
    TaxonomicFilterValue,
    isQuickFilterItem,
} from 'lib/components/TaxonomicFilter/types'

export function keywordShortcutValue(item: QuickFilterItem): string {
    // Synthetic identity string used only as a React/selection key. Never parsed by consumers.
    return JSON.stringify({
        q: item.propertyKey,
        v: item.filterValue,
        e: item.eventName ?? null,
    })
}

export type BaseGroupFns<T> = {
    getName: (instance: T) => string
    getValue: (instance: T) => TaxonomicFilterValue
    getIcon?: (instance: T) => JSX.Element
    getPopoverHeader: (instance: T) => string
}

/** Extend a group's presentation methods so they also handle `QuickFilterItem`s (keyword
 *  shortcuts), and attach a `keywordShortcuts` builder. `popoverHeader` lets each group label
 *  its own shortcut kind (e.g. "Autocapture shortcut" for series, "Event type shortcut" for
 *  property filters). */
export function withKeywordShortcuts<T>(
    base: BaseGroupFns<T>,
    {
        popoverHeader,
        buildShortcuts,
    }: {
        popoverHeader: string
        buildShortcuts: (searchQuery: string) => QuickFilterItem[]
    }
): Pick<TaxonomicFilterGroup, 'getName' | 'getValue' | 'getIcon' | 'getPopoverHeader' | 'keywordShortcuts'> {
    const baseGetIcon = base.getIcon
    return {
        getName: (item: T | QuickFilterItem) => (isQuickFilterItem(item) ? item.name : base.getName(item)),
        getValue: (item: T | QuickFilterItem) =>
            isQuickFilterItem(item) ? keywordShortcutValue(item) : base.getValue(item),
        getIcon: baseGetIcon
            ? (item: T | QuickFilterItem) => (isQuickFilterItem(item) ? <IconCursor /> : baseGetIcon(item))
            : undefined,
        getPopoverHeader: (item: T | QuickFilterItem) =>
            isQuickFilterItem(item) ? popoverHeader : base.getPopoverHeader(item),
        keywordShortcuts: buildShortcuts,
    }
}
