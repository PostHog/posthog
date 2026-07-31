import { ReactNode } from 'react'

import { IconCheckCircle } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { IconRadioButtonUnchecked } from 'lib/lemon-ui/icons'

export const ROW_ACTION_REVEAL_CLASSES =
    'opacity-0 group-hover/row:opacity-100 group-focus-within/row:opacity-100 transition-opacity'

export function ReadToggleIcon({ read }: { read: boolean }): JSX.Element {
    if (read) {
        return <IconCheckCircle className="size-4 text-success" />
    }
    return (
        <>
            <IconRadioButtonUnchecked className="size-4 text-muted opacity-40 group-hover/read:hidden" />
            <IconCheckCircle className="size-4 text-muted opacity-60 hidden group-hover/read:block" />
        </>
    )
}

export function NotificationActionButton({
    icon,
    tooltip,
    onClick,
    tone = 'default',
    ariaLabel,
    className,
}: {
    icon: ReactNode
    tooltip?: string
    onClick: (e: React.MouseEvent) => void
    tone?: 'default' | 'danger'
    ariaLabel?: string
    className?: string
}): JSX.Element {
    const toneClasses =
        tone === 'danger'
            ? 'text-secondary hover:text-danger hover:bg-fill-error-highlight'
            : 'text-secondary hover:text-primary hover:bg-fill-highlight-200'

    const button = (
        <button
            type="button"
            aria-label={ariaLabel ?? tooltip}
            className={`min-w-[26px] min-h-[26px] flex items-center justify-center rounded cursor-pointer ${toneClasses} ${
                className ?? ''
            }`}
            onClick={onClick}
        >
            {icon}
        </button>
    )

    return tooltip ? <Tooltip title={tooltip}>{button}</Tooltip> : button
}
