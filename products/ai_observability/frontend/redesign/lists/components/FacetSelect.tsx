import { useState } from 'react'

import { IconSearch } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDropdown, LemonInput, LemonSkeleton } from '@posthog/lemon-ui'

export interface FacetSelectProps {
    /** Singular, sentence case: "Model". */
    label: string
    /** Undefined while the options load. */
    options: string[] | undefined
    value: string[]
    onChange: (value: string[]) => void
    'data-attr': string
}

const MAX_SHOWN = 100

export function FacetSelect({ label, options, value, onChange, 'data-attr': dataAttr }: FacetSelectProps): JSX.Element {
    const [search, setSearch] = useState('')
    // A selected value that dropped out of the window still shows, so it can be cleared.
    const all = [...value.filter((selected) => !options?.includes(selected)), ...(options ?? [])]
    const shown = all.filter((option) => option.toLowerCase().includes(search.toLowerCase())).slice(0, MAX_SHOWN)
    const summary = value.length === 0 ? null : value.length === 1 ? value[0] : `${value.length} selected`

    return (
        <LemonDropdown
            closeOnClickInside={false}
            placement="bottom-start"
            overlay={
                <div className="flex w-64 flex-col gap-1">
                    <LemonInput
                        type="search"
                        size="small"
                        autoFocus
                        prefix={<IconSearch />}
                        placeholder={`Search ${label.toLowerCase()}s`}
                        value={search}
                        onChange={setSearch}
                    />
                    {options === undefined ? (
                        <LemonSkeleton repeat={4} className="h-6" />
                    ) : shown.length === 0 ? (
                        <span className="px-2 py-1 text-xs text-secondary">No matches</span>
                    ) : (
                        <ul className="ph-no-capture m-0 max-h-72 list-none overflow-y-auto p-0">
                            {shown.map((option) => (
                                <li key={option}>
                                    <LemonCheckbox
                                        fullWidth
                                        size="small"
                                        label={<span className="truncate font-mono text-xs">{option}</span>}
                                        checked={value.includes(option)}
                                        onChange={(checked) =>
                                            onChange(
                                                checked
                                                    ? [...value, option]
                                                    : value.filter((selected) => selected !== option)
                                            )
                                        }
                                    />
                                </li>
                            ))}
                        </ul>
                    )}
                    {value.length > 0 ? (
                        <LemonButton size="small" fullWidth center onClick={() => onChange([])}>
                            Clear
                        </LemonButton>
                    ) : null}
                </div>
            }
        >
            <LemonButton
                type="secondary"
                size="small"
                active={value.length > 0}
                // Values are raw event data, so keep them out of autocapture and replay.
                className={value.length > 0 ? 'ph-no-capture' : undefined}
                data-attr={dataAttr}
            >
                {summary ? (
                    <span className="flex max-w-48 items-center gap-1">
                        <span className="text-secondary">{label}</span>
                        <span className="truncate">{summary}</span>
                    </span>
                ) : (
                    label
                )}
            </LemonButton>
        </LemonDropdown>
    )
}
