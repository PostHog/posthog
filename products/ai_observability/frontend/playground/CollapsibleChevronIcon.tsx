import { IconChevronRight } from '@posthog/icons'

export function CollapsibleChevronIcon({ collapsed }: { collapsed: boolean }): JSX.Element {
    return (
        <IconChevronRight
            className={`h-3.5 w-3.5 shrink-0 transition-transform ${collapsed ? 'rotate-0' : 'rotate-90'}`}
        />
    )
}
