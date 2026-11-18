import {
    Badge,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { RoleType } from '~/types'

type RoleItem = { value: string | null; label: string }

export function QuillDefaultRoleSelector({
    roles,
    value,
    onChange,
    loading,
    disabledReason,
}: {
    roles: RoleType[]
    value: string | null
    onChange: (value: string | null) => void
    loading?: boolean
    disabledReason?: string | null
}): JSX.Element {
    const items: RoleItem[] = [
        { value: null, label: 'No default role' },
        ...roles.map((role) => ({ value: role.id, label: role.name })),
    ]

    const trigger = (
        <SelectValue>
            {(selected: string | null) =>
                items.find((item) => item.value === selected)?.label ?? (
                    <span className="text-muted-foreground">Select a default role...</span>
                )
            }
        </SelectValue>
    )

    return (
        <div className="max-w-80">
            <Select<string | null>
                items={items}
                value={value}
                onValueChange={(next) => onChange(next as string | null)}
                disabled={loading || !!disabledReason}
            >
                {disabledReason ? (
                    <Tooltip>
                        <TooltipTrigger delay={0} render={<SelectTrigger className="w-full" />}>
                            {trigger}
                        </TooltipTrigger>
                        <TooltipContent>{disabledReason}</TooltipContent>
                    </Tooltip>
                ) : (
                    <SelectTrigger className="w-full">{trigger}</SelectTrigger>
                )}
                <SelectContent>
                    {items.map((item) => (
                        <SelectItem key={item.value ?? 'none'} value={item.value}>
                            <span className="flex items-center gap-2">
                                {item.label}
                                {item.value !== null && item.value === value && <Badge>Current default</Badge>}
                            </span>
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
        </div>
    )
}
