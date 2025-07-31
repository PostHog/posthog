import { IconCheckCircle } from '@posthog/icons'
import clsx from 'clsx'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { ReactNode } from 'react'

interface SelectableCardProps {
    title: string
    description: ReactNode
    selected: boolean
    onClick: () => void
    disabled?: boolean
    disabledReason?: string
    className?: string
}

export function SelectableCard({
    title,
    description,
    selected,
    onClick,
    disabled = false,
    disabledReason,
    className,
}: SelectableCardProps): JSX.Element {
    const card = (
        <div
            className={clsx(
                'flex-1 cursor-pointer p-4 rounded border transition-colors',
                selected ? 'border-accent bg-accent-highlight-secondary' : 'border-primary',
                !disabled && 'hover:border-accent-dark',
                disabled && 'opacity-50 cursor-not-allowed',
                className
            )}
            onClick={disabled ? undefined : onClick}
            role="button"
            tabIndex={disabled ? -1 : 0}
            onKeyDown={(e) => {
                if (!disabled && (e.key === 'Enter' || e.key === ' ')) {
                    e.preventDefault()
                    onClick()
                }
            }}
            aria-pressed={selected}
            aria-disabled={disabled}
        >
            <div className="font-semibold flex justify-between items-center">
                <span>{title}</span>
                {selected && <IconCheckCircle fontSize={18} color="var(--accent)" />}
            </div>
            <div className="text-secondary text-sm leading-relaxed mt-1">{description}</div>
        </div>
    )

    if (disabled && disabledReason) {
        return <Tooltip title={disabledReason}>{card}</Tooltip>
    }

    return card
}
