import { Fragment, forwardRef, useEffect, useRef, useState } from 'react'

import { IconInfo, IconMinusSmall, IconSearch, IconX } from '@posthog/icons'

import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ListBox } from 'lib/ui/ListBox/ListBox'
import {
    PopoverPrimitive,
    PopoverPrimitiveContent,
    PopoverPrimitiveTrigger,
} from 'lib/ui/PopoverPrimitive/PopoverPrimitive'

import { ScrollableShadows } from '../ScrollableShadows/ScrollableShadows'

type Category = { label: string; value: string; hint?: string; icon?: React.ReactNode }
type Suggestion = { label: string; value: string; hint?: string; icon?: React.ReactNode }
type Hint = string

export interface SearchAutocompleteProps {
    inputPlaceholder?: string
    onChange?: (value: string) => void
    onClear?: () => void
    onKeyDown?: (e: React.KeyboardEvent<HTMLInputElement>) => void
    onSelect?: (value: string) => void
    searchData?: [Category, Suggestion[] | undefined, Hint?][]
    autoFocus?: boolean
    includeNegation?: boolean
    defaultValue?: string
}

// Handles structured autocomplete with support for category:value and negation (! or -) inputs
export const SearchAutocomplete = forwardRef<HTMLDivElement, SearchAutocompleteProps>(
    (
        {
            inputPlaceholder,
            onChange,
            onSelect,
            searchData,
            autoFocus,
            onClear,
            onKeyDown,
            includeNegation = false,
            defaultValue,
        },
        ref
    ): JSX.Element => {
        const [value, setValue] = useState(defaultValue ?? '')
        const [open, setOpen] = useState(false)
        const [suggestions, setSuggestions] = useState<Suggestion[]>([])
        const [currentHint, setCurrentHint] = useState<string | undefined>(undefined)
        const inputRef = useRef<HTMLInputElement>(null)

        // Base category suggestions (e.g. "user", "type", "name")
        const baseCategories: Suggestion[] = searchData?.map(([cat]) => cat) || []

        // Extracts the last space-separated token for parsing
        const getLastToken = (input: string): string => {
            const tokens = input.trim().split(/\s+/)
            return tokens[tokens.length - 1]
        }

        // Core logic for determining dropdown content based on current input value
        const getSuggestions = (input: string): [Suggestion[], string?] => {
            const lastToken = getLastToken(input).trim()
            const hasColon = lastToken.includes(':')
            const isNegated = includeNegation && (lastToken.startsWith('!') || lastToken.startsWith('-'))
            const cleanToken = isNegated ? lastToken.slice(1) : lastToken
            const [rawCategory, rawValue = ''] = cleanToken.split(':')
            const matchedCategory = searchData?.find(([cat]) => cat.label === rawCategory)

            const value = rawValue.trim()
            const cleanValue = value.startsWith('!') || value.startsWith('-') ? value.slice(1) : value

            const suffixes = [':']
            const isValueEntryPoint = suffixes.some((suffix) => input.trim().endsWith(`${rawCategory}${suffix}`))
            const endsWithSpace = input.endsWith(' ')

            const excludeOption: Suggestion = {
                label: 'exclude…',
                value: '!__placeholder__',
                hint: 'Exclude the following',
                icon: <IconMinusSmall />,
            }

            // "user:me " → new token begins, show base categories again
            if (endsWithSpace) {
                return [baseCategories, undefined]
            }

            // Empty input → show categories
            if (lastToken === '') {
                if (includeNegation) {
                    return [[...baseCategories, excludeOption], undefined]
                }
                return [baseCategories, undefined]
            }

            // Typing a category like "us" or "!us" → suggest matching categories
            if (!hasColon) {
                const matches = baseCategories.filter((cat) =>
                    cat.label.toLowerCase().startsWith(cleanToken.toLowerCase())
                )
                return [matches, undefined]
            }

            // "user:" → suggest values
            if (matchedCategory && isValueEntryPoint) {
                const base = matchedCategory[1] || []
                return [base, matchedCategory[2]]
            }

            // Full match (e.g. user:me or !user:me) → no further suggestions
            if (
                matchedCategory &&
                matchedCategory[1]?.some((s) => s.value.toLowerCase() === cleanValue.toLowerCase())
            ) {
                return [[], undefined]
            }

            // Partial match → filter values
            if (matchedCategory && matchedCategory[1]) {
                const filtered = matchedCategory[1].filter((s) =>
                    s.label.toLowerCase().startsWith(cleanValue.toLowerCase())
                )

                return [isNegated ? filtered : filtered, matchedCategory[2]]
            }

            return [[], undefined]
        }

        const handleChange = (val: string): void => {
            setValue(val)

            if (searchData) {
                if (val.length === 0) {
                    setSuggestions(baseCategories)
                    setCurrentHint(undefined)
                    onChange?.(val)
                    return
                }

                const [newSuggestions, newHint] = getSuggestions(val)
                setSuggestions(newSuggestions)
                setCurrentHint(newHint)
                setOpen(newSuggestions.length > 0 || !!newHint)
            }
            onChange?.(val)
        }

        const handleSuggestionClick = (suggestion: Suggestion): void => {
            const tokens = value.trim().split(/\s+/)
            const lastToken = getLastToken(value)
            const isNegated = lastToken.startsWith('!') || lastToken.startsWith('-')
            const cleanToken = isNegated ? lastToken.slice(1) : lastToken
            const category = cleanToken.split(':')[0]
            const matched = searchData?.find(([cat]) => cat.label === category)

            const isCategory = searchData?.some(([cat]) => cat.label === suggestion.value)
            const inputEndsWithSpace = value.endsWith(' ')
            let newInput = ''
            const negationPrefix = isNegated ? lastToken[0] : ''

            // e.g. clicking "user" turns input into "user:" or "!user:"
            if (isCategory) {
                tokens[inputEndsWithSpace ? tokens.length : tokens.length - 1] = `${negationPrefix}${suggestion.value}:`
                newInput = tokens.join(' ').trim()
                setValue(newInput)
                focusInput()

                const [newSuggestions, newHint] = getSuggestions(newInput)
                setSuggestions(newSuggestions)
                setCurrentHint(newHint)
                setOpen(newSuggestions.length > 0 || !!newHint)
                return
            }

            // Handle "exclude…" placeholder → converts input to !user:
            if (suggestion.value === '!__placeholder__' && includeNegation) {
                tokens[tokens.length - 1] = isNegated ? `-` : `!`
                const newVal = tokens.join(' ')
                setValue(newVal)
                focusInput()

                setSuggestions(baseCategories)
                setCurrentHint(undefined)
                setOpen(true)
                return
            }

            // Selecting value (e.g. "me") → commit and refresh
            if (matched && matched[1]) {
                tokens[tokens.length - 1] = `${negationPrefix}${category}:${suggestion.value}`
                newInput = tokens.join(' ').trim()
                setValue(newInput)
                focusInput()
                onSelect?.(suggestion.value)

                const [newSuggestions, newHint] = getSuggestions(newInput)
                setSuggestions(newSuggestions)
                setCurrentHint(newHint)
                setOpen(newSuggestions.length > 0 || !!newHint)
            }

            onChange?.(newInput)
        }

        const handleKeydown = (e: React.KeyboardEvent<HTMLInputElement>): void => {
            if (!open || suggestions.length === 0) {
                onKeyDown?.(e)
                return
            }

            if (e.key === 'Enter') {
                setOpen(false)
                return
            }
        }

        const focusInput = (): void => {
            if (!searchData) {
                return
            }
            const input = inputRef.current
            if (input) {
                input.focus()
                const length = input.value.length
                input.setSelectionRange(length, length)
            }
        }

        useEffect(() => {
            setValue(defaultValue ?? '')
        }, [defaultValue])

        return (
            <ListBox className="w-full" virtualFocus>
                <PopoverPrimitive open={open} onOpenChange={setOpen}>
                    <ListBox.Item asChild virtualFocusIgnore>
                        <PopoverPrimitiveTrigger asChild>
                            <LemonInput
                                type="text"
                                placeholder={inputPlaceholder}
                                className="w-full"
                                onChange={(val) => handleChange(val)}
                                value={value}
                                onKeyDown={handleKeydown}
                                inputRef={inputRef}
                                aria-label="Search input"
                                aria-expanded={open}
                                aria-controls="suggestions-list"
                                aria-autocomplete="list"
                                size="small"
                                data-attr="tree-search-autocomplete-input"
                                prefix={
                                    <div className="flex items-center justify-center size-4 ml-[2px] mr-px">
                                        <IconSearch className="size-4" />
                                    </div>
                                }
                                suffix={
                                    value && onClear ? (
                                        <ButtonPrimitive
                                            size="sm"
                                            iconOnly
                                            onClick={() => {
                                                setValue('')
                                                setSuggestions(baseCategories)
                                                onClear()
                                            }}
                                            data-attr="tree-search-autocomplete-clear-button"
                                            className="bg-transparent [&_svg]:opacity-50 hover:[&_svg]:opacity-100 focus-visible:[&_svg]:opacity-100 -mr-px"
                                            tooltip="Clear search"
                                        >
                                            <IconX className="size-4" />
                                        </ButtonPrimitive>
                                    ) : null
                                }
                                autoFocus={autoFocus}
                            />
                        </PopoverPrimitiveTrigger>
                    </ListBox.Item>

                    {searchData && open && (
                        <PopoverPrimitiveContent
                            ref={ref}
                            onCloseAutoFocus={(e) => e.preventDefault()}
                            onOpenAutoFocus={(e) => {
                                e.preventDefault()
                                const [newSuggestions, newHint] = getSuggestions(value)
                                const isSatisfied = newSuggestions.length === 0 && !newHint
                                if (isSatisfied) {
                                    setOpen(false)
                                    return
                                }
                                setSuggestions(newSuggestions)
                                setCurrentHint(newHint)
                            }}
                            align="start"
                            className="primitive-menu-content min-w-[var(--radix-popover-trigger-width)] max-w-none max-h-[calc(var(--radix-popover-content-available-height)-var(--radix-popover-trigger-height))]"
                        >
                            <ScrollableShadows
                                direction="vertical"
                                styledScrollbars
                                innerClassName="primitive-menu-content-inner p-1"
                            >
                                <ListBox.Item asChild key={value} aria-disabled="true">
                                    <ButtonPrimitive
                                        menuItem
                                        disabled
                                        data-attr="tree-search-autocomplete-type-to-search-disabled-button"
                                    >
                                        <IconSearch className="size-4" />
                                        {value ? value : 'Type to search...'}
                                    </ButtonPrimitive>
                                </ListBox.Item>

                                {suggestions.map((item) => (
                                    <Fragment key={item.value}>
                                        {item.value === '!__placeholder__' ? (
                                            <div className="-mx-1 my-1 h-px bg-border-primary" />
                                        ) : null}
                                        <ListBox.Item asChild>
                                            <ButtonPrimitive
                                                onClick={() => handleSuggestionClick(item)}
                                                menuItem
                                                data-attr={`tree-search-autocomplete-suggestion-${item.value}-button`}
                                            >
                                                <div className="flex items-center justify-center size-4 text-tertiary">
                                                    {item.icon}
                                                </div>
                                                {item.label}
                                                {item.hint ? (
                                                    <span className="text-xxs text-tertiary italic pt-1">
                                                        {item.hint}
                                                    </span>
                                                ) : null}
                                            </ButtonPrimitive>
                                        </ListBox.Item>
                                    </Fragment>
                                ))}
                                {currentHint && (
                                    <ButtonPrimitive
                                        menuItem
                                        className="px-2 py-1 text-sm text-tertiary"
                                        disabled
                                        data-attr="tree-search-autocomplete-hint-disabled-button"
                                    >
                                        <IconInfo /> {currentHint}
                                    </ButtonPrimitive>
                                )}
                            </ScrollableShadows>
                        </PopoverPrimitiveContent>
                    )}
                </PopoverPrimitive>
            </ListBox>
        )
    }
)

SearchAutocomplete.displayName = 'SearchAutocomplete'
