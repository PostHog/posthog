import { useMemo, useRef, useState } from 'react'

import { IconBolt, IconChevronDown } from '@posthog/icons'
import {
    Button,
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    ComboboxTrigger,
    Text,
} from '@posthog/quill'

const CUSTOM_PREFIX = '__custom__:'
const NONE_VALUE = '__none__'
const MAX_OPTIONS = 150

function sameText(value: string): string {
    return value
}

export interface SearchPickerProps {
    value: string | null
    onChange: (value: string | null) => void
    options: string[]
    loading: boolean
    error?: string | null
    placeholder: string
    searchPlaceholder: string
    ariaLabel: string
    allowNone?: boolean
    noneLabel?: string
    format?: (value: string) => string
    onSearchChange?: (search: string) => void
    onOpen?: () => void
}

/** A searchable list of values. Typing a value that is not in the list offers it as a custom one. */
export function SearchPicker({
    value,
    onChange,
    options,
    loading,
    error,
    placeholder,
    searchPlaceholder,
    ariaLabel,
    allowNone,
    noneLabel = 'None',
    format = sameText,
    onSearchChange,
    onOpen,
}: SearchPickerProps): JSX.Element {
    const [open, setOpen] = useState(false)
    const [search, setSearchState] = useState('')
    const setSearch = (next: string): void => {
        setSearchState(next)
        onSearchChange?.(next)
    }
    const anchorRef = useRef<HTMLDivElement>(null)
    const items = useMemo(() => {
        const needle = search.trim().toLowerCase()
        const base = value && !options.includes(value) ? [value, ...options] : options
        const matches = needle
            ? base.filter(
                  (option) => option.toLowerCase().includes(needle) || format(option).toLowerCase().includes(needle)
              )
            : base
        const exact = base.some((option) => option.toLowerCase() === needle)
        const custom = needle && !exact ? [`${CUSTOM_PREFIX}${search.trim()}`] : []
        return [...(allowNone && !needle ? [NONE_VALUE] : []), ...matches.slice(0, MAX_OPTIONS), ...custom]
    }, [search, options, value, allowNone, format])

    const choose = (next: string | null): void => {
        setOpen(false)
        setSearch('')
        if (next === null) {
            return
        }
        if (next === NONE_VALUE) {
            onChange(null)
            return
        }
        onChange(next.startsWith(CUSTOM_PREFIX) ? next.slice(CUSTOM_PREFIX.length) : next)
    }

    return (
        <div ref={anchorRef} className="w-full">
            <Combobox
                items={items}
                filter={null}
                value={value ?? NONE_VALUE}
                onValueChange={(next) => choose(next as string | null)}
                open={open}
                onOpenChange={(next) => {
                    setOpen(next)
                    if (next) {
                        onOpen?.()
                    } else {
                        setSearch('')
                    }
                }}
                inputValue={search}
                onInputValueChange={(next) => setSearch(next ?? '')}
                modal={false}
            >
                <ComboboxTrigger
                    render={
                        <Button
                            variant="outline"
                            size="sm"
                            className="w-full min-w-0 justify-between"
                            aria-label={ariaLabel}
                        >
                            <span className="min-w-0 truncate">
                                {value ? format(value) : allowNone ? noneLabel : placeholder}
                            </span>
                            <IconChevronDown />
                        </Button>
                    }
                />
                <ComboboxContent anchor={anchorRef} side="bottom" align="start" sideOffset={4} className="w-64">
                    <ComboboxInput placeholder={searchPlaceholder} showTrigger={false} />
                    {error && (
                        <Text size="xs" variant="destructive" role="alert">
                            {error}
                        </Text>
                    )}
                    <ComboboxEmpty>{loading ? 'Loading…' : 'No matches. Type a name to use it anyway.'}</ComboboxEmpty>
                    <ComboboxList className="max-h-72">
                        {(item: string) => {
                            if (item === NONE_VALUE) {
                                return (
                                    <ComboboxItem key={item} value={item}>
                                        <Text size="xs" variant="muted" render={<span />}>
                                            {noneLabel}
                                        </Text>
                                    </ComboboxItem>
                                )
                            }
                            if (item.startsWith(CUSTOM_PREFIX)) {
                                const raw = item.slice(CUSTOM_PREFIX.length)
                                return (
                                    <ComboboxItem key={item} value={item}>
                                        <IconBolt className="shrink-0" />
                                        <span className="min-w-0 truncate">Use “{raw}”</span>
                                    </ComboboxItem>
                                )
                            }
                            return (
                                <ComboboxItem key={item} value={item} title={item}>
                                    <span className="min-w-0 flex-1 truncate">{format(item)}</span>
                                    {format(item) !== item ? (
                                        <Text
                                            size="xs"
                                            variant="muted"
                                            render={<span />}
                                            className="shrink-0 font-mono"
                                            translate="no"
                                        >
                                            {item}
                                        </Text>
                                    ) : null}
                                </ComboboxItem>
                            )
                        }}
                    </ComboboxList>
                </ComboboxContent>
            </Combobox>
        </div>
    )
}
