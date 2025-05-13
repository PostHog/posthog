import { IconSearch, IconX } from "@posthog/icons"
import { LemonInput } from "lib/lemon-ui/LemonInput"
import { useEffect } from 'react';
import { ButtonPrimitive } from "lib/ui/Button/ButtonPrimitives"
import { ListBox, ListBoxHandle } from "lib/ui/ListBox/ListBox"
import {
    PopoverPrimitive,
    PopoverPrimitiveContent,
    PopoverPrimitiveTrigger,
} from "lib/ui/PopoverPrimitive/PopoverPrimitive"
import { forwardRef, useState, useRef } from "react"

type Category = string
type Suggestion = { label: string; value: string }
type Hint = string

export interface SearchWithTagsProps {
    inputPlaceholder?: string
    defaultSearchTerm?: string
    onChange?: (value: string) => void
    onClear?: () => void
    onKeyDown?: (e: React.KeyboardEvent<HTMLInputElement>) => void
    className?: string
    defaultOpen?: boolean
    alwaysOpen?: boolean
    onSelect?: (value: string) => void
    searchData: [Category, Suggestion[] | undefined, Hint?][]
    autoFocus?: boolean
}

export const SearchTagAutocomplete = forwardRef<HTMLInputElement, SearchWithTagsProps>(
    (
        {
            inputPlaceholder,
            onChange,
            onSelect,
            searchData,
            autoFocus,
            onClear,
        },
        _
    ): JSX.Element => {
        const [value, setValue] = useState('')
        const [open, setOpen] = useState(false)
        const [suggestions, setSuggestions] = useState<Suggestion[]>([])
        const [currentHint, setCurrentHint] = useState<string | undefined>(undefined)
        const inputRef = useRef<HTMLInputElement>(null)
        const listBoxRef = useRef<ListBoxHandle>(null)

        const baseCategories = searchData.map(([cat]) => ({ value: cat, label: cat }))

        const getLastToken = (input: string) => {
            const tokens = input.trim().split(/\s+/)
            return tokens[tokens.length - 1]
        }

        const getSuggestions = (input: string): [Suggestion[], string?] => {
            const lastToken = getLastToken(input).trim()
            const hasColon = lastToken.includes(":")
            const [rawCategory, rawValue = ""] = lastToken.split(":")
            const matchedCategory = searchData.find(([cat]) => cat === rawCategory)
        
            const value = rawValue.trim()
            const cleanValue = value.startsWith("!") || value.startsWith("-") ? value.slice(1) : value
        
            const suffixes = [":", ":!", ":-"]
            const isValueEntryPoint = suffixes.some((suffix) =>
                input.trim().endsWith(`${rawCategory}${suffix}`)
            )
        
            const isNegated =
                lastToken === `${rawCategory}:!` ||
                lastToken === `${rawCategory}:-` ||
                rawValue.startsWith("!") ||
                rawValue.startsWith("-")

            console.log('isNegated', isNegated)
        
            if (lastToken === "") {
                return [baseCategories, undefined]
            }
        
            if (!hasColon) {
                const matches = baseCategories.filter((cat) =>
                    cat.label.toLowerCase().startsWith(lastToken.toLowerCase())
                )
                return [matches, undefined]
            }
        
            if (matchedCategory && isValueEntryPoint) {
                const base = matchedCategory[1] || []
                const excludeOption: Suggestion = {
                    label: "Exclude…",
                    value: "!__placeholder__",
                }
        
                return [isNegated ? base : [excludeOption, ...base], matchedCategory[2]]
            }
        
            if (
                matchedCategory &&
                matchedCategory[1]?.some((s) => s.value.toLowerCase() === cleanValue.toLowerCase())
            ) {
                return [[], undefined] // Fully satisfied token → no more suggestions
            }
        
            if (matchedCategory && matchedCategory[1]) {
                const filtered = matchedCategory[1].filter((s) =>
                    s.label.toLowerCase().startsWith(cleanValue.toLowerCase())
                )
        
                const excludeOption: Suggestion = {
                    label: "Exclude…",
                    value: "!__placeholder__",
                }
        
                const results = isNegated ? filtered : [excludeOption, ...filtered]
                return [results, matchedCategory[2]]
            }
        
            return [[], undefined]
        }
        

        const handleChange = (val: string) => {
            setValue(val)

            const inputEndsWithSpace = val.endsWith(" ")

            if (val.length === 0) {
                setSuggestions(baseCategories)
                setCurrentHint(undefined)
                setOpen(false)
                onChange?.(val)
                return
            }

            if (inputEndsWithSpace) {
                setSuggestions(baseCategories)
                setCurrentHint(undefined)
                setOpen(true)
                onChange?.(val)
                return
            }

            const [newSuggestions, newHint] = getSuggestions(val)

            setSuggestions(newSuggestions)
            setCurrentHint(newHint)
            setOpen(newSuggestions.length > 0 || !!newHint)

            onChange?.(val)
        }

        const handleSuggestionClick = (suggestion: Suggestion) => {
            const tokens = value.trim().split(/\s+/)
            const lastToken = getLastToken(value)
            const [category, partialRaw = ""] = lastToken.split(":")
            const matched = searchData.find(([cat]) => cat === category)
        
            const isCategory = searchData.some(([cat]) => cat === suggestion.value)
            const inputEndsWithSpace = value.endsWith(" ")
        
            let newInput = ""
        
            if (isCategory) {
                if (inputEndsWithSpace || value === "") {
                    tokens.push(`${suggestion.value}:`)
                } else {
                    tokens[tokens.length - 1] = `${suggestion.value}:`
                }
        
                newInput = tokens.join(" ").trim()
                setValue(newInput)
                focusInput()
        
                const [newSuggestions, newHint] = getSuggestions(newInput)
                setSuggestions(newSuggestions)
                setCurrentHint(newHint)
                setOpen(newSuggestions.length > 0 || !!newHint)
                return
            }
        
            if (matched && suggestion.value === "!__placeholder__") {
                const newVal = `${category}:!`
                setValue(newVal)
                focusInput()
        
                const [newSuggestions, newHint] = getSuggestions(newVal)
                setSuggestions(newSuggestions)
                setCurrentHint(newHint)
                setOpen(newSuggestions.length > 0 || !!newHint)
                return
            }
        
            if (matched && matched[1]) {
                const negationPrefix = partialRaw.startsWith("!") || partialRaw.startsWith("-") ? partialRaw[0] : ""
                tokens[tokens.length - 1] = `${category}:${negationPrefix}${suggestion.value}`
                newInput = tokens.join(" ").trim()
                setValue(newInput)
                focusInput()
                onSelect?.(suggestion.value)
        
                const [newSuggestions, newHint] = getSuggestions(newInput)
                setSuggestions(newSuggestions)
                setCurrentHint(newHint)
                setOpen(newSuggestions.length > 0 || !!newHint)
            }
        }        

        const handleKeydown = (e: React.KeyboardEvent<HTMLInputElement>) => {
            if (!open || suggestions.length === 0) return

            if (e.key === 'ArrowDown') {
                e.preventDefault()
                listBoxRef.current?.focusFirstElement()
            } else if (e.key === 'ArrowUp') {
                e.preventDefault()
                listBoxRef.current?.focusNthElement(suggestions.length - 1)
            } else if (e.key === 'Enter') {
                setOpen(false)
            }
        }

        const focusInput = () => {
            const input = inputRef.current
            if (input) {
                input.focus()
                const length = input.value.length
                input.setSelectionRange(length, length)
            }
        }

        return (
            <PopoverPrimitive open={open} onOpenChange={setOpen}>
                <PopoverPrimitiveTrigger asChild>
                    <LemonInput
                        type="text"
                        placeholder={inputPlaceholder}
                        className="w-full"
                        onChange={(val) => handleChange(val)}
                        value={value}
                        onKeyDown={handleKeydown}
                        aria-label="Search input"
                        // onFocus={() => {
                        //     if (value.trim() === "") {
                        //         setSuggestions(baseCategories)
                        //     }
                        // }}
                        onFocus={() => {
                            const [newSuggestions, newHint] = getSuggestions(value)
                            setSuggestions(newSuggestions)
                            setCurrentHint(newHint)
                            // setOpen(newSuggestions.length > 0 || !!newHint)
                        }}
                        inputRef={inputRef}
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
                                    onClick={() => onClear()}
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
                {open && (
                    <PopoverPrimitiveContent
                        onCloseAutoFocus={(e) => {
                            e.preventDefault()
                        }}
                        onOpenAutoFocus={(e) => e.preventDefault()}
                        className="primitive-menu-content w-[var(--radix-popover-trigger-width)] max-w-none"
                    >
                        <ListBox ref={listBoxRef} className="flex flex-col gap-px p-1">
                            {suggestions.map((item) => (
                                <>
                                    <ListBox.Item asChild key={item.value}>
                                        <ButtonPrimitive
                                            onClick={() => handleSuggestionClick(item)}
                                            menuItem
                                    >
                                            {item.label}
                                        </ButtonPrimitive>
                                    </ListBox.Item>
                                    {item.value === "!__placeholder__" ? (
                                        <div className="-mx-1 my-1 h-px bg-border-primary"/>
                                    ) : null}
                                </>
                            ))}
                            {currentHint && (
                                <div className="px-2 py-1 text-sm text-muted">
                                    {currentHint}
                                </div>
                            )}
                        </ListBox>
                    </PopoverPrimitiveContent>
                )}
            </PopoverPrimitive>
        )
    }
)
