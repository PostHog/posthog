import { useRef, useState } from 'react'

import {
    Button,
    Combobox,
    ComboboxCollection,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxGroup,
    ComboboxInput,
    ComboboxItem,
    ComboboxLabel,
    ComboboxList,
    ComboboxSeparator,
    SelectTriggerIcon,
} from '@posthog/quill'

import {
    CURRENCY_SYMBOL_TO_EMOJI_MAP,
    CURRENCY_SYMBOL_TO_NAME_MAP,
    DISABLED_CURRENCIES,
    IMPORTANT_CURRENCIES,
    OTHER_CURRENCIES,
} from 'lib/utils/currency'

import { CurrencyCode } from '~/queries/schema/schema-general'

type CurrencyGroup = { label: string; items: CurrencyCode[] }

const CURRENCY_GROUPS: CurrencyGroup[] = [
    { label: 'Most Popular', items: IMPORTANT_CURRENCIES },
    { label: 'Other currencies', items: OTHER_CURRENCIES },
]

function currencyLabel(currency: CurrencyCode): string {
    return `${CURRENCY_SYMBOL_TO_NAME_MAP[currency]} (${currency})`
}

export function QuillCurrencyDropdown({
    value,
    onChange,
    disabledReason,
}: {
    value: CurrencyCode | null
    onChange: (currency: CurrencyCode) => void
    disabledReason?: string
}): JSX.Element {
    const [open, setOpen] = useState(false)
    const triggerRef = useRef<HTMLButtonElement>(null)

    return (
        <Combobox<CurrencyCode>
            items={CURRENCY_GROUPS}
            open={open}
            onOpenChange={setOpen}
            value={value}
            onValueChange={(next) => {
                if (next) {
                    onChange(next)
                }
                setOpen(false)
            }}
            itemToStringLabel={currencyLabel}
        >
            <Button
                ref={triggerRef}
                variant="outline"
                left
                className="w-fit"
                onClick={() => setOpen(!open)}
                disabledReason={disabledReason}
            >
                <span className="min-w-0 truncate">
                    {value ? `${CURRENCY_SYMBOL_TO_EMOJI_MAP[value]} ${currencyLabel(value)}` : 'Select currency'}
                </span>
                <SelectTriggerIcon />
            </Button>
            <ComboboxContent anchor={triggerRef} className="w-80">
                <ComboboxInput placeholder="Search currencies" showTrigger={false} />
                <ComboboxEmpty>No matching currencies</ComboboxEmpty>
                <ComboboxList>
                    {(group: CurrencyGroup, index: number) => (
                        <ComboboxGroup key={group.label} items={group.items}>
                            {index > 0 ? <ComboboxSeparator /> : null}
                            <ComboboxLabel>{group.label}</ComboboxLabel>
                            <ComboboxCollection>
                                {(currency: CurrencyCode) => (
                                    <ComboboxItem
                                        key={currency}
                                        value={currency}
                                        disabledReason={DISABLED_CURRENCIES[currency]}
                                    >
                                        {CURRENCY_SYMBOL_TO_EMOJI_MAP[currency]} {currencyLabel(currency)}
                                    </ComboboxItem>
                                )}
                            </ComboboxCollection>
                        </ComboboxGroup>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
