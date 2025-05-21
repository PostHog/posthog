import { IconInfo, IconSearch, IconX } from '@posthog/icons'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ListBox } from 'lib/ui/ListBox/ListBox'
import {
    PopoverPrimitive,
    PopoverPrimitiveContent,
    PopoverPrimitiveTrigger,
} from 'lib/ui/PopoverPrimitive/PopoverPrimitive'
import { forwardRef, useRef, useState } from 'react'

type Category = { label: string; hint?: string }
type Suggestion = { label: string; value: string; hint?: string }
type Hint = string

export interface SearchAutocompleteProps {
    inputPlaceholder?: string
    defaultSearchTerm?: string
    onChange?: (value: string) => void
    onClear?: () => void
    onKeyDown?: (e: React.KeyboardEvent<HTMLInputElement>) => void
    onSelect?: (value: string) => void
    searchData: [Category, Suggestion[] | undefined, Hint?][]
    autoFocus?: boolean
}

// Handles structured autocomplete with support for category:value and negation (! or -) inputs
export const SearchAutocomplete = forwardRef<HTMLDivElement, SearchAutocompleteProps>(
    ({ inputPlaceholder, onChange, onSelect, searchData, autoFocus, onClear, onKeyDown }, ref): JSX.Element => {
        const [value, setValue] = useState('')
        const [open, setOpen] = useState(false)
        const [suggestions, setSuggestions] = useState<Suggestion[]>([])
        const [currentHint, setCurrentHint] = useState<string | undefined>(undefined)
        const inputRef = useRef<HTMLInputElement>(null)

        // Base category suggestions (e.g. "user", "type", "name")
        const baseCategories: Suggestion[] = searchData.map(([cat]) => ({
            value: cat.label,
            label: cat.label,
            hint: cat.hint,
        }))

        // Extracts the last space-separated token for parsing
        const getLastToken = (input: string): string => {
            const tokens = input.trim().split(/\s+/)
            return tokens[tokens.length - 1]
        }

        // Core logic for determining dropdown content based on current input value
        const getSuggestions = (input: string): [Suggestion[], string?] => {
            const lastToken = getLastToken(input).trim()
            const hasColon = lastToken.includes(':')
            const [rawCategory, rawValue = ''] = lastToken.split(':')
            const matchedCategory = searchData.find(([cat]) => cat.label === rawCategory)

            const value = rawValue.trim()
            const cleanValue = value.startsWith('!') || value.startsWith('-') ? value.slice(1) : value

            const suffixes = [':', ':!', ':-']
            const isValueEntryPoint = suffixes.some((suffix) => input.trim().endsWith(`${rawCategory}${suffix}`))
            const endsWithSpace = input.endsWith(' ')

            const excludeOption: Suggestion = {
                label: 'Exclude…',
                value: '!__placeholder__',
                hint: 'Exclude the following',
            }

            // "user:me " → new token begins, show base categories again
            if (endsWithSpace) {
                return [baseCategories, undefined]
            }

            // user:! or user:- or user:!me → treated as negated value input
            const isNegated =
                lastToken === `${rawCategory}:!` ||
                lastToken === `${rawCategory}:-` ||
                rawValue.startsWith('!') ||
                rawValue.startsWith('-')

            // Empty input → show categories
            if (lastToken === '') {
                return [baseCategories, undefined]
            }

            // Typing a category like "us" → suggest matching categories
            if (!hasColon) {
                const matches = baseCategories.filter((cat) =>
                    cat.label.toLowerCase().startsWith(lastToken.toLowerCase())
                )
                return [matches, undefined]
            }

            // "user:" → suggest values (with optional "Exclude…" option)
            if (matchedCategory && isValueEntryPoint) {
                const base = matchedCategory[1] || []
                return [isNegated ? base : [excludeOption, ...base], matchedCategory[2]]
            }

            // Full match (e.g. user:me or user:!me) → no further suggestions
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

                return [isNegated ? filtered : [excludeOption, ...filtered], matchedCategory[2]]
            }

            return [[], undefined]
        }

        const handleChange = (val: string): void => {
            setValue(val)

            if (val.length === 0) {
                setSuggestions(baseCategories)
                setCurrentHint(undefined)
                setOpen(false)
                onChange?.(val)
                return
            }

            const [newSuggestions, newHint] = getSuggestions(val)

            setSuggestions(newSuggestions)
            setCurrentHint(newHint)
            setOpen(newSuggestions.length > 0 || !!newHint)
            onChange?.(val)
        }

        const handleSuggestionClick = (suggestion: Suggestion): void => {
            const tokens = value.trim().split(/\s+/)
            const lastToken = getLastToken(value)
            const [category, partialRaw = ''] = lastToken.split(':')
            const matched = searchData.find(([cat]) => cat.label === category)

            const isCategory = searchData.some(([cat]) => cat.label === suggestion.value)
            const inputEndsWithSpace = value.endsWith(' ')
            let newInput = ''

            // e.g. clicking "user" turns input into "user:"
            if (isCategory) {
                tokens[inputEndsWithSpace ? tokens.length : tokens.length - 1] = `${suggestion.value}:`
                newInput = tokens.join(' ').trim()
                setValue(newInput)
                focusInput()

                const [newSuggestions, newHint] = getSuggestions(newInput)
                setSuggestions(newSuggestions)
                setCurrentHint(newHint)
                setOpen(newSuggestions.length > 0 || !!newHint)
                return
            }

            // Handle "Exclude…" placeholder → converts input to user:!
            if (matched && suggestion.value === '!__placeholder__') {
                tokens[tokens.length - 1] = `${category}:!`
                const newVal = tokens.join(' ').trim()
                setValue(newVal)
                focusInput()

                const [newSuggestions, newHint] = getSuggestions(newVal)
                setSuggestions(newSuggestions)
                setCurrentHint(newHint)
                setOpen(newSuggestions.length > 0 || !!newHint)
                return
            }

            // Selecting value (e.g. "me") → commit and refresh
            if (matched && matched[1]) {
                const negationPrefix = partialRaw.startsWith('!') || partialRaw.startsWith('-') ? partialRaw[0] : ''
                tokens[tokens.length - 1] = `${category}:${negationPrefix}${suggestion.value}`
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

            if (e.key === 'ArrowDown') {
                // e.preventDefault()
                // listBoxRef.current?.focusFirstElement() // allow keyboard to enter dropdown
                return
            } else if (e.key === 'ArrowUp') {
                // e.preventDefault()
                // listBoxRef.current?.focusNthElement(suggestions.length - 1)
                return
            } else if (e.key === 'Enter') {
                setOpen(false)
                return
            }
        }

        const focusInput = (): void => {
            const input = inputRef.current
            if (input) {
                input.focus()
                const length = input.value.length
                input.setSelectionRange(length, length)
            }
        }

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

                    {open && (
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
                            className="primitive-menu-content min-w-[var(--radix-popover-trigger-width)] max-w-none"
                        >
                            <ul className="flex flex-col gap-px p-1">
                                <ListBox.Item asChild key={value} aria-disabled="true">
                                    <ButtonPrimitive menuItem disabled>
                                        <IconSearch className="size-4" />
                                        {value ? value : 'Type to search...'}
                                    </ButtonPrimitive>
                                </ListBox.Item>

                                {suggestions.map((item) => (
                                    <>
                                        <ListBox.Item asChild key={item.value}>
                                            <ButtonPrimitive onClick={() => handleSuggestionClick(item)} menuItem>
                                                {item.label}{' '}
                                                {item.hint ? (
                                                    <span className="text-xxs text-tertiary italic pt-1">
                                                        {item.hint}
                                                    </span>
                                                ) : null}
                                            </ButtonPrimitive>
                                        </ListBox.Item>
                                        {item.value === '!__placeholder__' ? (
                                            <div className="-mx-1 my-1 h-px bg-border-primary" />
                                        ) : null}
                                    </>
                                ))}
                                {currentHint && (
                                    <div className="px-2 py-1 text-sm text-tertiary">
                                        <IconInfo /> {currentHint}
                                    </div>
                                )}
                            </ul>
                        </PopoverPrimitiveContent>
                    )}
                </PopoverPrimitive>
            </ListBox>
        )
    }
)

SearchAutocomplete.displayName = 'SearchAutocomplete'
