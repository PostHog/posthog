import {
    Button,
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { ALL_VALUE } from './variables'

interface DashboardV2MultiSelectVariableProps {
    label: string
    options: string[]
    includeAll: boolean
    values: string[]
    onChange: (values: string[]) => void
}

export function DashboardV2MultiSelectVariable({
    label,
    options,
    includeAll,
    values,
    onChange,
}: DashboardV2MultiSelectVariableProps): JSX.Element {
    const all = values.includes(ALL_VALUE)
    const picked = values.filter((value) => value !== ALL_VALUE)
    const summary = all ? 'All' : picked.length ? picked.join(', ') : 'None'

    const toggle = (option: string, checked: boolean): void => {
        const next = checked ? [...picked, option] : picked.filter((value) => value !== option)
        onChange(next.length || !includeAll ? next : [ALL_VALUE])
    }

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={<Button variant="outline" className="max-w-64" data-attr="dashboard-v2-variable-multi" />}
            >
                <span>{label}:</span>
                <span className="truncate" translate="no">
                    {summary}
                </span>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
                {includeAll && (
                    <>
                        <DropdownMenuCheckboxItem checked={all} onCheckedChange={() => onChange([ALL_VALUE])}>
                            All
                        </DropdownMenuCheckboxItem>
                        <DropdownMenuSeparator />
                    </>
                )}
                {options.map((option) => (
                    <DropdownMenuCheckboxItem
                        key={option}
                        checked={!all && picked.includes(option)}
                        onCheckedChange={(checked) => toggle(option, checked)}
                    >
                        {option}
                    </DropdownMenuCheckboxItem>
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
