import type { ComponentType, ReactNode } from 'react'
import { useState } from 'react'

import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    cn,
} from '@posthog/quill'

import { FilterBarControlChip } from './FilterBarControlChip'
import { useFilterBarControl } from './filterBarControls'

// Radio values are strings, so the unset value needs a stand-in.
const DEFAULT_OPTION = '__default'

export interface FilterBarOption {
    value: string
    label: string
    disabledReason?: string
}

export interface FilterBarOptionControlProps {
    id: string
    label: string
    icon: ComponentType<{ className?: string }>
    value: string | null
    options: FilterBarOption[]
    onChange: (value: string | null) => void
    /**
     * What the default means on this surface, such as "Each insight's interval". With it, the chip always shows and
     * offers the default as an option. Without it, the chip waits in the add menu until an option is picked.
     */
    defaultLabel?: string
    footer?: ReactNode
    'data-attr': string
}

export function FilterBarOptionControl({
    id,
    label,
    icon,
    value,
    options,
    onChange,
    defaultLabel,
    footer,
    'data-attr': dataAttr,
}: FilterBarOptionControlProps): JSX.Element | null {
    const [open, setOpen] = useState(false)
    const hasValue = value != null
    const persistent = defaultLabel != null

    useFilterBarControl({
        id,
        label,
        icon,
        hasValue,
        persistent,
        // The add menu closes on the same click, so wait a frame before opening, or its dismissal closes this too.
        open: () => requestAnimationFrame(() => setOpen(true)),
        clear: () => onChange(null),
    })

    if (!persistent && !hasValue && !open) {
        return null
    }

    const valueText = hasValue ? (options.find((option) => option.value === value)?.label ?? value) : defaultLabel

    return (
        <FilterBarControlChip
            icon={icon}
            label={label}
            onRemove={hasValue ? () => onChange(null) : undefined}
            data-attr={dataAttr}
        >
            <DropdownMenu open={open} onOpenChange={setOpen} modal={false}>
                <DropdownMenuTrigger
                    render={
                        <Button
                            variant="outline"
                            className={cn('min-w-0 max-w-64', !valueText && 'text-muted-foreground')}
                        />
                    }
                    data-attr={`${dataAttr}-value`}
                >
                    <span className="truncate">{valueText ?? 'Pick an option'}</span>
                </DropdownMenuTrigger>
                <DropdownMenuContent>
                    <DropdownMenuRadioGroup
                        value={value ?? DEFAULT_OPTION}
                        onValueChange={(next) => onChange(next === DEFAULT_OPTION ? null : (next as string))}
                    >
                        {persistent && (
                            <DropdownMenuRadioItem value={DEFAULT_OPTION} closeOnClick>
                                {defaultLabel}
                            </DropdownMenuRadioItem>
                        )}
                        {options.map((option) => (
                            <DropdownMenuRadioItem
                                key={option.value}
                                value={option.value}
                                disabledReason={option.disabledReason}
                                closeOnClick
                            >
                                {option.label}
                            </DropdownMenuRadioItem>
                        ))}
                    </DropdownMenuRadioGroup>
                    {footer && (
                        <>
                            <DropdownMenuSeparator />
                            {footer}
                        </>
                    )}
                </DropdownMenuContent>
            </DropdownMenu>
        </FilterBarControlChip>
    )
}
