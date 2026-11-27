import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { FilterPillContent } from '../bar/FilterPillContent'
import type { FilterControlProps } from '../filterDefinition'
import type { BreakdownFilterConfig, BreakdownFilterValue } from './breakdownFilterSpec'

export function BreakdownFilter({
    filter,
    value,
    onChange,
    defaultOpen,
}: FilterControlProps<BreakdownFilterConfig, BreakdownFilterValue>): JSX.Element {
    const { options } = filter.config
    const pickedIndex = options.findIndex((option) => option.type === value?.type && option.key === value?.key)
    const picked = options[pickedIndex]
    return (
        <DropdownMenu defaultOpen={defaultOpen}>
            <DropdownMenuTrigger
                render={<Button size="sm" variant="outline" data-attr="dashboard-v2-filter-breakdown" />}
            >
                <FilterPillContent label={filter.label ?? 'Breakdown'} summary={picked?.label ?? value?.key} />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
                <DropdownMenuRadioGroup
                    value={pickedIndex >= 0 ? String(pickedIndex) : ''}
                    onValueChange={(index: string) => {
                        const { type, key } = options[Number(index)]
                        onChange({ type, key })
                    }}
                >
                    {options.map((option, index) => (
                        <DropdownMenuRadioItem key={`${option.type}:${option.key}`} value={String(index)}>
                            {option.label}
                        </DropdownMenuRadioItem>
                    ))}
                </DropdownMenuRadioGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
