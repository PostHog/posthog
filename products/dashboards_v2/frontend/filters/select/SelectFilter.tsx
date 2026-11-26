import {
    Button,
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { FilterPillContent } from '../bar/FilterPillContent'
import { type FilterControlProps, summarizeValues } from '../filterDefinition'
import type { SelectFilterConfig, SelectFilterValue } from './selectFilterSpec'

export function SelectFilter({
    filter,
    value = [],
    onChange,
    defaultOpen,
}: FilterControlProps<SelectFilterConfig, SelectFilterValue>): JSX.Element {
    // A value picked before the option was removed still shows, so it can be cleared.
    const options = [...new Set([...filter.config.options, ...value])]
    const toggle = (option: string, checked: boolean): void => {
        const next = checked ? [...value, option] : value.filter((picked) => picked !== option)
        onChange(next.length > 0 ? next : undefined)
    }
    return (
        <DropdownMenu defaultOpen={defaultOpen}>
            <DropdownMenuTrigger render={<Button size="sm" variant="outline" data-attr="dashboard-v2-filter-select" />}>
                <FilterPillContent
                    label={filter.label ?? filter.config.key}
                    summary={value.length > 0 ? summarizeValues(value) : undefined}
                />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
                <DropdownMenuGroup>
                    {options.map((option) => (
                        <DropdownMenuCheckboxItem
                            key={option}
                            checked={value.includes(option)}
                            onCheckedChange={(checked) => toggle(option, checked)}
                            closeOnClick={false}
                        >
                            {option}
                        </DropdownMenuCheckboxItem>
                    ))}
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
