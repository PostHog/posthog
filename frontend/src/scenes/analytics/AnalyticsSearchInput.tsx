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
    return (
        <InputGroup className="h-8 w-56 max-w-full">
            <InputGroupAddon align="inline-start">
                <InputGroupText>
                    <IconSearch />
                </InputGroupText>
            </InputGroupAddon>
            <InputGroupInput
                type="search"
                aria-label={label}
                placeholder={placeholder}
                value={value}
                onChange={(event: React.ChangeEvent<HTMLInputElement>) => onChange(event.target.value)}
                onKeyDown={(event: React.KeyboardEvent<HTMLInputElement>) => {
                    if (event.key === 'Escape' && value !== '') {
                        event.preventDefault()
                        event.stopPropagation()
                        onChange('')
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
                        onClick={() => onChange('')}
                        data-attr={`${dataAttr}-clear`}
                    >
                        <IconX />
                    </InputGroupButton>
                </InputGroupAddon>
            )}
        </InputGroup>
    )
}
