import { useMemo } from 'react'

/**
 * Variation: TaxonomicFilter input as a Base UI Combobox (autocomplete).
 *
 * Drop-in alternative to `<TaxonomicFilter.Input>` — instead of just a text
 * field that drives a separate `<Panel>`, this version wires the Quill
 * `<Combobox>` primitive (base-ui Combobox under the hood) so suggestions
 * appear in a popup beneath the input as the user types.
 *
 * Two ways to use it:
 *
 *   1. **Compact picker (no Panel)** — render only `<AutocompleteInput>` and
 *      optionally `<Categories>` for tab switching. The popup contains the
 *      active tab's items and is the only selection surface.
 *
 *   2. **Hybrid (Panel below input)** — render `<AutocompleteInput>` *and*
 *      `<Panel>`. Both show the same items (cache is shared). Useful while
 *      doing a side-by-side visual review.
 *
 * Selection on the popup forwards to the orchestrator's `selectItem`, same as
 * clicking a row in `<Panel>`. Keyboard nav inside the popup is owned by
 * Combobox; the orchestrator's `rootProps.onKeyDown` is bypassed for keys
 * Combobox consumes (Up/Down/Enter/Escape).
 */
import {
    Combobox,
    ComboboxCollection,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
} from '@posthog/quill'

import { useGroupList } from '../hooks/useGroupList'
import { TaxonomicDefinitionTypes, TaxonomicFilterGroup } from '../types'
import { useTaxonomicFilterContext } from './context'

export interface TaxonomicFilterAutocompleteInputProps {
    placeholder?: string
    className?: string
    /** Override the Combobox popup className (e.g. width, max-height). */
    popupClassName?: string
    /** Maximum visible items in the popup. Default 50 — popup-mode is meant
     *  to be lighter-weight than the full Panel. */
    maxItems?: number
    /** Render a blank chevron-only trigger button beside the input. Default true. */
    showTrigger?: boolean
}

export function TaxonomicFilterAutocompleteInput({
    placeholder,
    className,
    popupClassName,
    maxItems = 50,
    showTrigger = true,
}: TaxonomicFilterAutocompleteInputProps): JSX.Element | null {
    const { activeGroup, inputProps, selectItem, searchQuery, setSearchQuery } = useTaxonomicFilterContext()
    if (!activeGroup) {
        return null
    }
    return (
        <TaxonomicAutocompleteForGroup
            key={activeGroup.type}
            group={activeGroup}
            inputValue={searchQuery}
            setSearchQuery={setSearchQuery}
            inputPlaceholder={placeholder ?? inputProps.placeholder}
            className={className}
            popupClassName={popupClassName}
            maxItems={maxItems}
            showTrigger={showTrigger}
            onSelect={selectItem}
        />
    )
}

interface TaxonomicAutocompleteForGroupProps {
    group: TaxonomicFilterGroup
    inputValue: string
    setSearchQuery: (q: string) => void
    inputPlaceholder?: string
    className?: string
    popupClassName?: string
    maxItems: number
    showTrigger: boolean
    onSelect: (group: TaxonomicFilterGroup, value: string | number | null, item: any) => void
}

function TaxonomicAutocompleteForGroup({
    group,
    inputValue,
    setSearchQuery,
    inputPlaceholder,
    className,
    popupClassName,
    maxItems,
    showTrigger,
    onSelect,
}: TaxonomicAutocompleteForGroupProps): JSX.Element {
    const { getGroupListInput } = useTaxonomicFilterContext()
    const list = useGroupList(getGroupListInput(group))

    // Cap items shown in the popup to keep render cost low. The full count
    // remains available via the Categories badge / Panel.
    const items = useMemo(() => list.items.slice(0, maxItems), [list.items, maxItems])

    return (
        <Combobox
            // Bypass Combobox's internal Fuse — we already filter via useGroupList.
            items={items}
            filteredItems={items}
            filter={null}
            inputValue={inputValue}
            onInputValueChange={(value) => setSearchQuery(value ?? '')}
            onValueChange={(item) => {
                if (!item) {
                    return
                }
                const itemValue = group.getValue?.(item) ?? null
                onSelect(group, itemValue, item)
            }}
            itemToStringLabel={(item: TaxonomicDefinitionTypes) =>
                group.getName?.(item) ??
                ('name' in (item as Record<string, unknown>) ? ((item as { name?: string }).name ?? '') : '')
            }
        >
            <ComboboxInput
                className={className}
                placeholder={inputPlaceholder}
                showTrigger={showTrigger}
                data-attr="taxonomic-filter-searchfield"
            >
                <ComboboxContent className={popupClassName}>
                    <ComboboxEmpty>
                        {list.needsMoreSearchCharacters
                            ? 'Type more to search'
                            : list.isLoading
                              ? 'Loading…'
                              : 'No matches'}
                    </ComboboxEmpty>
                    <ComboboxList>
                        <ComboboxCollection items={items}>
                            {(item: TaxonomicDefinitionTypes) => {
                                const label =
                                    group.getName?.(item) ??
                                    ('name' in (item as Record<string, unknown>)
                                        ? ((item as { name?: string }).name ?? '')
                                        : '')
                                return (
                                    <ComboboxItem key={String(group.getValue?.(item) ?? label)} value={item}>
                                        {label}
                                    </ComboboxItem>
                                )
                            }}
                        </ComboboxCollection>
                    </ComboboxList>
                </ComboboxContent>
            </ComboboxInput>
        </Combobox>
    )
}
