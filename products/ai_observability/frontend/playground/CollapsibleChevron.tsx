import { IconChevronRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

export function CollapsibleChevron({ collapsed }: { collapsed: boolean }): JSX.Element {
    return (
        <LemonButton
            size="xsmall"
            noPadding
            className="h-5 w-5 [&_svg]:h-3.5 [&_svg]:w-3.5"
            icon={<IconChevronRight className={`transition-transform ${collapsed ? 'rotate-0' : 'rotate-90'}`} />}
        />
    )
}
