import { IconChevronRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

// aria-expanded belongs on a wrapping element, not here: LemonButton paints
// [aria-expanded='true'] with its active background, which reads as a stuck grey state.
export function CollapsibleChevron({ collapsed, ariaLabel }: { collapsed: boolean; ariaLabel?: string }): JSX.Element {
    return (
        <LemonButton
            size="xsmall"
            noPadding
            className="h-5 w-5 [&_svg]:h-3.5 [&_svg]:w-3.5"
            icon={<IconChevronRight className={`transition-transform ${collapsed ? 'rotate-0' : 'rotate-90'}`} />}
            aria-label={ariaLabel}
        />
    )
}
