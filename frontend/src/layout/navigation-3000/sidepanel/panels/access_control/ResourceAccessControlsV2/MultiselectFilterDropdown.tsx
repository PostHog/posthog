import { useMemo, useState } from 'react'

import { LemonButton, LemonCheckbox, LemonInput, Link } from '@posthog/lemon-ui'

export function MultiSelectFilterDropdown<T extends string = string>(props: {
    title: string
    placeholder: string
    options: { key: T; label: string }[]
    values: T[]
    setValues: (values: T[]) => void
}): JSX.Element {
    const [searchTerm, setSearchTerm] = useState('')

    const filteredOptions = useMemo(() => {
        return props.options.filter((option) => option.label.toLowerCase().includes(searchTerm.toLowerCase()))
    }, [props.options, searchTerm])

    return (
        <div className="w-96 flex flex-col min-h-0 overflow-hidden max-h-[80vh]">
            <div className="p-2 border-b space-y-2">
                <div className="flex justify-between items-center">
                    <span className="font-bold text-xs uppercase tracking-widest text-muted-alt">{props.title}</span>
                    {props.values.length ? (
                        <Link
                            to="#"
                            className="text-xs"
                            onClick={(e) => {
                                e.preventDefault()
                                props.setValues([])
                            }}
                        >
                            Clear
                        </Link>
                    ) : null}
                </div>
                <LemonInput
                    type="search"
                    placeholder={props.placeholder}
                    value={searchTerm}
                    onChange={setSearchTerm}
                    autoFocus
                    size="small"
                    fullWidth
                />
            </div>
            <div className="flex-1 overflow-y-auto p-1 min-h-0">
                {filteredOptions.length > 0 ? (
                    <div className="flex flex-col gap-px">
                        {filteredOptions.map((option) => (
                            <LemonButton
                                key={option.key}
                                fullWidth
                                size="small"
                                type="tertiary"
                                onClick={() => {
                                    if (props.values.includes(option.key)) {
                                        props.setValues(props.values.filter((v) => v !== option.key))
                                    } else {
                                        props.setValues([...props.values, option.key])
                                    }
                                }}
                            >
                                <div className="flex items-center gap-2">
                                    <LemonCheckbox checked={props.values.includes(option.key)} />
                                    <span className="flex-1 truncate font-normal">{option.label}</span>
                                </div>
                            </LemonButton>
                        ))}
                    </div>
                ) : (
                    <div className="p-2 text-muted-alt text-xs italic text-center">No options found</div>
                )}
            </div>
        </div>
    )
}
