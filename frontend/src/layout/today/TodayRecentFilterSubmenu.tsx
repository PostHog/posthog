import { ReactNode } from 'react'

import { DropdownMenuSub, DropdownMenuSubContent, DropdownMenuSubTrigger, cn } from '@posthog/quill'

interface TodayRecentFilterSubmenuProps {
    label: string
    /** The choice in force, shown beside the label. */
    value: string
    /** The choice differs from the default, so the value takes the primary color, like PostHog Desktop. */
    narrowed?: boolean
    children: ReactNode
}

export function TodayRecentFilterSubmenu({
    label,
    value,
    narrowed = false,
    children,
}: TodayRecentFilterSubmenuProps): JSX.Element {
    return (
        <DropdownMenuSub>
            <DropdownMenuSubTrigger>
                <span>{label}</span>
                <span
                    className={cn(
                        'flex-1 truncate pl-4 text-right',
                        narrowed ? 'text-primary' : 'text-muted-foreground'
                    )}
                >
                    {value}
                </span>
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent>{children}</DropdownMenuSubContent>
        </DropdownMenuSub>
    )
}
