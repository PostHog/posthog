import { useRef } from 'react'

import { IconSearch, IconX } from '@posthog/icons'
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput, InputGroupText } from '@posthog/quill'

/** The search field of the Analytics pages, with a clear button once there is text, like the chat search. */
export function AnalyticsSearchInput({
    value,
    onChange,
    label,
    placeholder,
    dataAttr,
}: {
    value: string
    onChange: (value: string) => void
    label: string
    placeholder: string
    dataAttr: string
}): JSX.Element {
    const inputRef = useRef<HTMLInputElement>(null)
    // The clear button unmounts once the field empties, which would drop focus to the page mid-search.
    const clear = (): void => {
        onChange('')
        inputRef.current?.focus()
    }
    return (
        <InputGroup className="h-8 w-56 max-w-full">
            <InputGroupAddon align="inline-start">
                <InputGroupText>
                    <IconSearch />
                </InputGroupText>
            </InputGroupAddon>
            <InputGroupInput
                ref={inputRef}
                type="search"
                aria-label={label}
                placeholder={placeholder}
                value={value}
                onChange={(event: React.ChangeEvent<HTMLInputElement>) => onChange(event.target.value)}
                onKeyDown={(event: React.KeyboardEvent<HTMLInputElement>) => {
                    if (event.key === 'Escape' && value !== '') {
                        event.preventDefault()
                        event.stopPropagation()
                        clear()
                    }
                }}
                // The browser's own clear button would sit next to this one.
                className="[&::-webkit-search-cancel-button]:hidden"
                data-attr={dataAttr}
            />
            {value !== '' && (
                <InputGroupAddon align="inline-end">
                    <InputGroupButton
                        size="icon-xs"
                        aria-label="Clear search"
                        onClick={clear}
                        data-attr={`${dataAttr}-clear`}
                    >
                        <IconX />
                    </InputGroupButton>
                </InputGroupAddon>
            )}
        </InputGroup>
    )
}
