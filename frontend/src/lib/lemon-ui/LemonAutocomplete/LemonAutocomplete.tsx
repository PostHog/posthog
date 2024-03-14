import Fuse from 'fuse.js'
import { useMemo, useState } from 'react'

import { LemonButton } from '../LemonButton'
import { LemonDropdown } from '../LemonDropdown'
import { LemonInput, LemonInputProps } from '../LemonInput'
import { LemonMenuItems } from '../LemonMenu/LemonMenu'
import { useKeyboardNavigation } from '../LemonMenu/useKeyboardNavigation'

export interface LemonAutocompleteOption {
    value: string
    label: string
}

export interface LemonAutocompletePropsBase
    extends Pick<LemonInputProps, 'autoFocus' | 'size' | 'allowClear' | 'fullWidth'> {
    options: LemonAutocompleteOption[]
    /** Callback fired when a value is selected, even if it already is set. */
    onSelect?: (newValue: string) => void
    placeholder?: string
    loading?: boolean
}

export interface LemonAutocompletePropsClearable extends LemonAutocompletePropsBase {
    allowClear: true
    /** Should only be undefined in form fields. */
    value?: string | null
    /** Callback fired when a value different from the one currently set is selected. */
    onChange?: (newValue: string | null) => void
}

export interface LemonAutocompletePropsNonClearable extends LemonAutocompletePropsBase {
    allowClear?: false
    /** Should only be undefined in form fields. */
    value?: string
    /** Callback fired when a value different from the one currently set is selected. */
    onChange?: (newValue: string) => void
}

export type LemonAutocompleteProps = LemonAutocompletePropsClearable | LemonAutocompletePropsNonClearable

export function LemonAutocomplete({
    // value = null,
    onChange,
    // onSelect,
    options,
    placeholder = 'Start typing',
    allowClear,
    // className,
    size,
    autoFocus,
    loading,
    fullWidth,
    ...props
}: LemonAutocompleteProps): JSX.Element {
    const [search, setSearch] = useState<string>('')
    const [showPopover, setShowPopover] = useState<boolean>(false)

    const { referenceRef, focusedItemIndex } = useKeyboardNavigation<HTMLInputElement, HTMLButtonElement>(
        options.length,
        0,
        false
    )

    const _onChange = (value: string | null): void => {
        setShowPopover(false)
        onChange(value)
    }

    const items: LemonMenuItems = options.map((o) => ({ label: o.label, onClick: () => _onChange(o.value) }))

    const fuse = useMemo(
        () =>
            new Fuse<LemonMenuItems>(items ?? [], {
                keys: ['label'],
                threshold: 0.3,
            }),
        [items]
    )

    const filteredItems = search
        ? [{ label: search, onClick: () => _onChange(search) }, ...fuse.search(search).map((result) => result.item)]
        : items ?? []

    return (
        <LemonDropdown
            closeOnClickInside={false}
            visible={showPopover}
            sameWidth
            actionable
            onVisibilityChange={(visible) => setShowPopover(visible)}
            overlay={
                <ul className="space-y-px">
                    {search && (
                        <li>
                            <LemonButton fullWidth role="menuitem" size="small" onClick={() => _onChange(search)}>
                                {search}
                            </LemonButton>
                        </li>
                    )}

                    {filteredItems.map((item, index) => (
                        <li key={item.label}>
                            <LemonButton
                                fullWidth
                                role="menuitem"
                                size="small"
                                onClick={() => _onChange(item.label)}
                                active={focusedItemIndex === index}
                            >
                                {item.label}
                            </LemonButton>
                        </li>
                    ))}

                    {loading ? (
                        <div className="p-2 text-muted-alt italic truncate border-t">Loading...</div>
                    ) : items.length === 0 ? (
                        <div className="p-2 text-muted-alt italic truncate border-t">No data</div>
                    ) : null}
                </ul>
            }
        >
            <LemonInput
                value={search}
                onChange={setSearch}
                allowClear={allowClear}
                placeholder={placeholder}
                size={size}
                autoFocus={autoFocus}
                fullWidth={fullWidth}
                ref={referenceRef}
                onPressEnter={() => _onChange(filteredItems[focusedItemIndex])}
            />
        </LemonDropdown>
    )
}
