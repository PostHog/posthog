import { LemonButton } from '@posthog/lemon-ui'

export interface SuggestionCardProps {
    title: string
    description?: string
    icon?: JSX.Element
    onClick: () => void
    /** Hover-style highlight, e.g. for keyboard navigation on the homepage. */
    active?: boolean
    className?: string
    onMouseEnter?: () => void
    onMouseLeave?: () => void
    'data-attr'?: string
}

/**
 * One suggestion row: icon + bold title + caption. Shared between the topic cards and the
 * homepage suggestions list so the two surfaces render identically.
 */
export function SuggestionCard({
    title,
    description,
    icon,
    onClick,
    active,
    className,
    onMouseEnter,
    onMouseLeave,
    'data-attr': dataAttr,
}: SuggestionCardProps): JSX.Element {
    return (
        <LemonButton
            className={className}
            fullWidth
            onClick={onClick}
            icon={icon}
            active={active}
            data-attr={dataAttr}
            onMouseEnter={onMouseEnter}
            onMouseLeave={onMouseLeave}
        >
            <div className="flex flex-col text-left leading-tight min-w-0">
                <span className="text-sm font-semibold truncate">{title}</span>
                {description && <span className="text-xs text-secondary font-normal truncate">{description}</span>}
            </div>
        </LemonButton>
    )
}
