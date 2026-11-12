import { useId, useState } from 'react'

import {
    Button,
    Combobox,
    ComboboxChip,
    ComboboxChips,
    ComboboxChipsInput,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxItem,
    ComboboxList,
    ComboboxValue,
    Skeleton,
    useComboboxAnchor,
} from '@posthog/quill'

const SCROLL_END_THRESHOLD_PX = 64

type TagsComboboxProps = {
    value: string[]
    onChange: (next: string[]) => void
    onOpen?: () => void
    onClose?: () => void
    onInputChange?: (input: string) => void
    loading?: boolean
    error?: string
    onRetry?: () => void
    /** Called when the list scrolls near its end, to load the next page. */
    onScrollEnd?: () => void
    loadingMore?: boolean
    options?: string[]
    placeholder?: string
    autoFocus?: boolean
    disabled?: boolean
    /** When true (default), typing a value not in options surfaces a "Create X" entry. */
    allowCustomValues?: boolean
    /** Label used in the "Create X" placeholder, e.g. "tag" → "Create new tag "foo"". */
    customValueNoun?: string
    /** data-attr applied to the input */
    dataAttr?: string
    className?: string
}

/**
 * Multi-select tag/chip input on Quill's Combobox. Mirrors the storybook "Multiple" pattern.
 * Adds a synthetic "Create X" item when the typed input doesn't match any option — selecting it
 * commits the typed value via `onChange`.
 */
export function TagsCombobox(props: TagsComboboxProps): JSX.Element {
    return <TagsComboboxInner {...props} />
}

function TagsComboboxInner({
    value,
    onChange,
    onOpen,
    onClose,
    onInputChange,
    loading,
    error,
    onRetry,
    onScrollEnd,
    loadingMore,
    options = [],
    placeholder,
    autoFocus,
    disabled,
    allowCustomValues = true,
    customValueNoun = 'tag',
    dataAttr,
    className,
}: TagsComboboxProps): JSX.Element {
    const [inputValue, setInputValue] = useState('')
    const createPrefix = `__create__${useId()}:`
    const trimmed = inputValue.trim()
    // While matches load, Enter would pick "Create" over an existing tag that hasn't arrived yet.
    // After a failed search, the Create row would hide the error and its retry.
    const showCreateItem =
        allowCustomValues &&
        !loading &&
        !error &&
        trimmed.length > 0 &&
        !value.includes(trimmed) &&
        !options.includes(trimmed)

    // Synthetic items list: existing options + (optionally) the "Create X" sentinel at the bottom.
    const items: string[] = [...options]
    const createSentinel = `${createPrefix}${trimmed}`
    if (showCreateItem) {
        items.push(createSentinel)
    }

    return (
        <Combobox
            multiple
            autoHighlight
            items={items}
            value={value}
            onValueChange={(next: string[], eventDetails) => {
                if (eventDetails.reason === 'escape-key') {
                    eventDetails.allowPropagation()
                    return
                }
                // Convert any sentinel selection into the real typed value, dedupe.
                const cleaned = (next ?? []).map((v) => (v === createSentinel ? trimmed : v))
                onChange(Array.from(new Set(cleaned)))
                setInputValue('')
            }}
            inputValue={inputValue}
            onInputValueChange={(v: string) => {
                setInputValue(v)
                onInputChange?.(v)
            }}
            onOpenChange={(open) => {
                if (open) {
                    onOpen?.()
                } else {
                    onClose?.()
                }
            }}
        >
            <TagsComboboxBody
                placeholder={placeholder}
                autoFocus={autoFocus}
                disabled={disabled}
                dataAttr={dataAttr}
                className={className}
                createSentinel={showCreateItem ? createSentinel : null}
                customValueNoun={customValueNoun}
                trimmed={trimmed}
                loading={loading}
                error={error}
                onRetry={onRetry}
                onScrollEnd={onScrollEnd}
                loadingMore={loadingMore}
            />
        </Combobox>
    )
}

function TagsComboboxBody({
    placeholder,
    autoFocus,
    disabled,
    dataAttr,
    className,
    createSentinel,
    customValueNoun,
    trimmed,
    loading,
    error,
    onRetry,
    onScrollEnd,
    loadingMore,
}: {
    placeholder?: string
    autoFocus?: boolean
    disabled?: boolean
    dataAttr?: string
    className?: string
    createSentinel: string | null
    customValueNoun: string
    trimmed: string
    loading?: boolean
    error?: string
    onRetry?: () => void
    onScrollEnd?: () => void
    loadingMore?: boolean
}): JSX.Element {
    const anchor = useComboboxAnchor()
    return (
        <>
            <ComboboxChips ref={anchor} className={className}>
                <ComboboxValue>
                    {(values) => (
                        <>
                            {(values as string[])
                                .filter((v) => v !== createSentinel)
                                .map((v) => (
                                    <ComboboxChip key={v} title={v}>
                                        {v}
                                    </ComboboxChip>
                                ))}
                            <ComboboxChipsInput
                                placeholder={placeholder}
                                autoFocus={autoFocus}
                                disabled={disabled}
                                data-attr={dataAttr}
                            />
                        </>
                    )}
                </ComboboxValue>
            </ComboboxChips>
            <ComboboxContent anchor={anchor}>
                <ComboboxEmpty>
                    {error ? (
                        <span className="flex items-center justify-between gap-2">
                            {error}
                            {onRetry && (
                                <Button size="sm" variant="outline" onClick={onRetry}>
                                    Try again
                                </Button>
                            )}
                        </span>
                    ) : loading ? (
                        <div
                            role="status"
                            aria-label={`Loading ${customValueNoun}s`}
                            className="flex w-56 flex-col gap-2"
                        >
                            <Skeleton className="h-3 w-3/4" />
                            <Skeleton className="h-3 w-1/2" />
                            <Skeleton className="h-3 w-2/3" />
                        </div>
                    ) : trimmed ? (
                        `No matching ${customValueNoun}s`
                    ) : (
                        `No ${customValueNoun}s yet`
                    )}
                </ComboboxEmpty>
                <ComboboxList
                    onScroll={
                        onScrollEnd
                            ? (event) => {
                                  const list = event.currentTarget
                                  if (
                                      list.scrollHeight - list.scrollTop - list.clientHeight <
                                      SCROLL_END_THRESHOLD_PX
                                  ) {
                                      onScrollEnd()
                                  }
                              }
                            : undefined
                    }
                >
                    {(item: string) => {
                        if (item === createSentinel) {
                            return (
                                <ComboboxItem key={item} value={item}>
                                    Create new {customValueNoun} "{trimmed}"
                                </ComboboxItem>
                            )
                        }
                        return (
                            <ComboboxItem key={item} value={item}>
                                {item}
                            </ComboboxItem>
                        )
                    }}
                </ComboboxList>
                {loadingMore && (
                    <div
                        role="status"
                        aria-label={`Loading more ${customValueNoun}s`}
                        className="flex flex-col gap-2 p-2"
                    >
                        <Skeleton className="h-3 w-3/4" />
                        <Skeleton className="h-3 w-1/2" />
                    </div>
                )}
            </ComboboxContent>
        </>
    )
}
