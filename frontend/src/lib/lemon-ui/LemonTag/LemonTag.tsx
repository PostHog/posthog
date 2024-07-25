import './LemonTag.scss'

import { IconEllipsis, IconX } from '@posthog/icons'
import clsx from 'clsx'
import { LemonButton, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { LemonButtonDropdown } from 'lib/lemon-ui/LemonButton'
import { forwardRef } from 'react'

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

export interface LemonTagProps {
    type?: LemonTagType
    children: React.ReactNode
    size?: 'small' | 'medium'
    weight?: 'normal'
    icon?: JSX.Element
    closable?: boolean
    onClose?: () => void
    onClick?: (e: React.MouseEvent<HTMLDivElement>) => void
    popover?: LemonButtonDropdown
    className?: string
    disabledReason?: string | null
    title?: string
    'data-attr'?: string
}

export const LemonTag: React.FunctionComponent<LemonTagProps & React.RefAttributes<HTMLDivElement>> = forwardRef(
    function LemonTag(
        {
            type = 'default',
            children,
            className,
            size = 'medium',
            weight,
            icon,
            closable,
            onClose,
            popover,
            disabledReason,
            ...props
        },
        ref
    ): JSX.Element {
        return (
            <div
                ref={ref}
                className={clsx(
                    'LemonTag',
                    `LemonTag--size-${size}`,
                    disabledReason ? 'cursor-not-allowed' : props.onClick ? 'cursor-pointer' : undefined,
                    `LemonTag--${type}`,
                    weight && `LemonTag--${weight}`,
                    className
                )}
                role={props.onClick ? 'button' : undefined}
                title={disabledReason || undefined}
                aria-disabled={disabledReason ? true : undefined}
                {...props}
            >
                {icon && <span className="LemonTag__icon">{icon}</span>}
                {children}
                {popover?.overlay && (
                    <LemonButtonWithDropdown
                        dropdown={popover}
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
                        icon={<IconX className="h-3.5 w-3.5" />}
                        onClick={onClose}
                        size="xsmall"
                        className="LemonTag__right-button"
                    />
                )}
            </div>
        )
    }
)
