import { useActions, useValues } from 'kea'
import { useMemo, useRef, useState } from 'react'

import { IconSearch } from '@posthog/icons'
import {
    Combobox,
    ComboboxCollection,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxGroup,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    ComboboxSeparator,
    ComboboxTrigger,
    InputGroupAddon,
    Text,
} from '@posthog/quill'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { libraryObjectName, productObjectType } from 'scenes/library/libraryUtils'
import { urls } from 'scenes/urls'

import { getNavProductItems } from '~/layout/panel-layout/navbar/tabs/navProductItems'
import { productMatchesSearch } from '~/layout/panel-layout/navbar/tabs/productsCatalog'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import { todayJumpBackPinLogic } from './todayJumpBackPinLogic'
import { todayLogic } from './todayLogic'
import { objectKey } from './todayRecentObjects'

const PRODUCT_LIMIT = 4

type PinOption = { key: string; entry: FileSystemEntry; label: string }
type PinGroup = { kind: 'pinned' | 'recent' | 'products' | 'items'; items: string[] }

function pinOption(entry: FileSystemEntry): PinOption {
    return { key: objectKey(entry), entry, label: libraryObjectName(entry) || 'Untitled' }
}

export function TodayJumpBackPinPicker({ trigger }: { trigger: JSX.Element }): JSX.Element | null {
    const { jumpBackPinScope, pinnedObjects, recentObjects } = useValues(todayLogic)
    const { toggleJumpBackPin } = useActions(todayLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const triggerRef = useRef<HTMLButtonElement>(null)
    const [open, setOpen] = useState(false)
    const [search, setSearch] = useState('')
    const {
        pinSearchResults: objects,
        pinSearchResultsLoading: loading,
        pinSearchFailed: failed,
    } = useValues(todayJumpBackPinLogic)
    const { loadPinSearchResults } = useActions(todayJumpBackPinLogic)
    const [pinnedOnOpen, setPinnedOnOpen] = useState<FileSystemEntry[]>([])

    const searching = search.trim().length > 0
    const pinnedKeys = useMemo(() => new Set(pinnedObjects.map(objectKey)), [pinnedObjects])

    const { groups, optionsByKey } = useMemo(() => {
        const products = getNavProductItems(featureFlags)
            .filter((item) => item.href && item.href !== urls.projectRoot() && productMatchesSearch(item, search))
            .slice(0, PRODUCT_LIMIT)
            .map((item) =>
                pinOption({
                    id: `product:${item.href}`,
                    path: item.displayLabel ?? item.path,
                    type: productObjectType(item),
                    href: item.href,
                })
            )
        const byKey = new Map<string, PinOption>()
        const take = (options: PinOption[]): string[] =>
            options.filter((option) => !byKey.has(option.key) && !!byKey.set(option.key, option)).map((o) => o.key)
        const result: PinGroup[] = (
            searching
                ? [
                      { kind: 'products' as const, items: take(products) },
                      { kind: 'items' as const, items: loading || failed ? [] : take(objects.map(pinOption)) },
                  ]
                : [
                      { kind: 'pinned' as const, items: take([...pinnedOnOpen, ...pinnedObjects].map(pinOption)) },
                      { kind: 'recent' as const, items: take(recentObjects.map(pinOption)) },
                  ]
        ).filter((group) => group.items.length > 0)
        return { groups: result, optionsByKey: byKey }
    }, [featureFlags, objects, loading, failed, search, searching, pinnedOnOpen, pinnedObjects, recentObjects])

    const statusNote = !searching
        ? null
        : loading
          ? 'Searching…'
          : failed
            ? 'Search failed. Change the search to try again.'
            : null

    if (!jumpBackPinScope) {
        return null
    }

    return (
        <Combobox
            items={groups}
            multiple
            filter={null}
            value={[...pinnedKeys]}
            inputValue={search}
            open={open}
            highlightItemOnHover
            itemToStringLabel={(key: string) => optionsByKey.get(key)?.label ?? ''}
            onInputValueChange={(value: string) => {
                setSearch(value)
                if (value.trim()) {
                    loadPinSearchResults(value)
                }
            }}
            onOpenChange={(next: boolean) => {
                setOpen(next)
                if (next) {
                    setPinnedOnOpen(pinnedObjects)
                } else {
                    setSearch('')
                }
            }}
            onValueChange={(next: string[]) => {
                const nextKeys = new Set(next)
                const key =
                    [...pinnedKeys].find((k) => !nextKeys.has(k)) ?? next.find((k) => !pinnedKeys.has(k)) ?? null
                const option = key ? optionsByKey.get(key) : null
                if (option) {
                    toggleJumpBackPin(jumpBackPinScope, option.entry)
                }
            }}
        >
            <ComboboxTrigger ref={triggerRef} render={trigger} />
            <ComboboxContent
                anchor={triggerRef}
                align="end"
                className="w-72 [&_[data-slot=combobox-input-group-wrapper]]:border-b-0"
            >
                <ComboboxInput
                    placeholder="Search products and items"
                    aria-label="Search products and items"
                    data-attr="today-home-recent-pin-search-input"
                    autoFocus
                    showTrigger={false}
                    className="h-7"
                >
                    <InputGroupAddon align="inline-start">
                        <IconSearch className="size-3" />
                    </InputGroupAddon>
                </ComboboxInput>
                <ComboboxList>
                    {(group: PinGroup) => (
                        <ComboboxGroup key={group.kind} items={group.items}>
                            {group.kind !== groups[0]?.kind ? <ComboboxSeparator /> : null}
                            <ComboboxCollection>
                                {(key: string) => (
                                    <ComboboxItem key={key} value={key} data-attr="today-home-recent-pin-pick">
                                        <span className="min-w-0 truncate">{optionsByKey.get(key)?.label}</span>
                                    </ComboboxItem>
                                )}
                            </ComboboxCollection>
                        </ComboboxGroup>
                    )}
                </ComboboxList>
                {statusNote ? (
                    <Text size="xs" variant="muted" render={<p />} className="m-0 px-2.5 py-1.5">
                        {statusNote}
                    </Text>
                ) : (
                    <ComboboxEmpty>
                        {searching ? 'Nothing matches' : 'Search for a product or item to pin'}
                    </ComboboxEmpty>
                )}
            </ComboboxContent>
        </Combobox>
    )
}
