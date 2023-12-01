import './LemonTag.scss'

import clsx from 'clsx'
import { IconClose, IconEllipsis } from 'lib/lemon-ui/icons'
import { LemonButton, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { LemonButtonDropdown } from 'lib/lemon-ui/LemonButton/LemonButton'

export type LemonTagType =
    | 'primary'
    | 'option'
    | 'highlight'
    | 'warning'
    | 'danger'
    | 'success'
    | 'default'
    | 'muted'
    | 'completion'
    | 'caution'
    | 'none'
    | 'breakdown'

export interface LemonTagProps extends React.HTMLAttributes<HTMLDivElement> {
    type?: LemonTagType
    children: React.ReactNode
    size?: 'small' | 'medium'
    weight?: 'normal'
    icon?: JSX.Element
    closable?: boolean
    onClose?: () => void
    popover?: LemonButtonDropdown
}

export function LemonTag({
    type = 'default',
    children,
    className,
    size = 'medium',
    weight,
    icon,
    closable,
    onClose,
    popover,
    ...props
}: LemonTagProps): JSX.Element {
    return (
        <div
            className={clsx(
                'LemonTag',
                `LemonTag--size-${size}`,
                !!props.onClick && 'cursor-pointer',
                `LemonTag--${type}`,
                weight && `LemonTag--${weight}`,
                className
            )}
            {...props}
        >
            {icon && <span className="LemonTag__icon">{icon}</span>}
            {children}
            {popover?.overlay && (
                <LemonButtonWithDropdown
                    dropdown={popover}
                    status="stealth"
                    size="small"
                    className="LemonTag__right-button"
                    icon={<IconEllipsis />}
                    onClick={(e) => {
                        e.stopPropagation()
                    }}
                />
            )}
            {closable && (
                <LemonButton
                    icon={<IconClose className="h-3.5 w-3.5" />}
                    onClick={onClose}
                    status="primary"
                    size="xsmall"
                    className="LemonTag__right-button"
                />
            )}
        </div>
    )
}
