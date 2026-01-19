import { useMemo, useState } from 'react'

import { LemonButton, LemonDropdown, LemonInput } from '@posthog/lemon-ui'

export function SearchableSelect(props: {
    value: string | null
    onChange: (value: string | null) => void
    options: { value: string; label: string }[]
    placeholder: string
    searchPlaceholder: string
    disabledReason?: string
}): JSX.Element {
    const [visible, setVisible] = useState(false)
    const [query, setQuery] = useState('')

    const selectedOption = useMemo(() => {
        return props.options.find((option) => option.value === props.value) ?? null
    }, [props.options, props.value])

    const filteredOptions = useMemo(() => {
        const search = query.trim().toLowerCase()
        if (!search) {
            return props.options
        }
        return props.options.filter((option) => option.label.toLowerCase().includes(search))
    }, [props.options, query])

    return (
        <LemonDropdown
            placement="bottom-start"
            closeOnClickInside={false}
            visible={visible}
            onVisibilityChange={setVisible}
            overlay={
                <div className="w-96 p-2 space-y-2">
                    <LemonInput value={query} onChange={setQuery} placeholder={props.searchPlaceholder} autoFocus />
                    <div className="max-h-80 overflow-y-auto">
                        {filteredOptions.length ? (
                            <div className="flex flex-col gap-px">
                                {filteredOptions.map((option) => (
                                    <LemonButton
                                        key={option.value}
                                        fullWidth
                                        type="tertiary"
                                        onClick={() => {
                                            props.onChange(option.value)
                                            setVisible(false)
                                        }}
                                    >
                                        {option.label}
                                    </LemonButton>
                                ))}
                            </div>
                        ) : (
                            <div className="text-secondary p-1">No results</div>
                        )}
                    </div>
                </div>
            }
        >
            <LemonButton
                fullWidth
                type="secondary"
                disabledReason={props.disabledReason}
                onClick={() => {
                    if (!visible) {
                        setQuery('')
                    }
                }}
            >
                {selectedOption?.label ?? props.placeholder}
            </LemonButton>
        </LemonDropdown>
    )
}
