import { IconX } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

interface TodayNavItemProps {
    title: string
    meta: string
    color: string
    icon: JSX.Element | null
    active?: boolean
    current?: boolean
    complete?: boolean
    thinking?: boolean
    entering?: boolean
    onClick: () => void
    onHoverChange?: (hovered: boolean) => void
    onRemove?: () => void
    dataAttr?: string
}

export function TodayNavItem({
    title,
    meta,
    color,
    icon,
    active = false,
    current = false,
    complete = false,
    thinking = false,
    entering = false,
    onClick,
    onHoverChange,
    onRemove,
    dataAttr,
}: TodayNavItemProps): JSX.Element {
    return (
        <div className={cn('TodayNavRow', entering && 'TodayNavRow--enter')}>
            <div className="TodayNavRow__inner">
                <button
                    type="button"
                    className="TodayNavItem"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ '--story-color': color } as React.CSSProperties}
                    data-active={active || current}
                    data-complete={complete}
                    data-thinking={thinking}
                    aria-current={current ? 'page' : undefined}
                    data-attr={dataAttr}
                    onClick={onClick}
                    onMouseEnter={() => onHoverChange?.(true)}
                    onMouseLeave={() => onHoverChange?.(false)}
                    onFocus={() => onHoverChange?.(true)}
                    onBlur={() => onHoverChange?.(false)}
                >
                    <span className="TodayNavItem__marker" aria-hidden>
                        {icon}
                    </span>
                    <span className="TodayNavItem__copy">
                        <span className="TodayNavItem__title">{title}</span>
                        <span className="TodayNavItem__meta">{meta}</span>
                    </span>
                </button>
                {complete && onRemove && (
                    <button
                        type="button"
                        className="TodayNavRow__remove"
                        aria-label={`Remove ${title}`}
                        data-attr="today-remove-story"
                        onClick={onRemove}
                    >
                        <IconX />
                    </button>
                )}
            </div>
        </div>
    )
}
