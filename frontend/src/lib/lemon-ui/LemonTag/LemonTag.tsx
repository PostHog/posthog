import './LemonTag.scss'

import { IconEllipsis, IconX } from '@posthog/icons'
import clsx from 'clsx'
import { LemonButton, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { LemonButtonDropdown } from 'lib/lemon-ui/LemonButton'
import { forwardRef, HTMLProps } from 'react'

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
    /** When true, the icon will swap to a close icon on hover and the entire tag becomes clickable to close */
    closeOnClick?: boolean
}

export const LemonTag: React.FunctionComponent<
    LemonTagProps & React.RefAttributes<HTMLDivElement> & Omit<HTMLProps<HTMLDivElement>, keyof LemonTagProps>
> = forwardRef(function LemonTag(
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
        closeOnClick,
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
                disabledReason
                    ? 'cursor-not-allowed'
                    : props.onClick || (closeOnClick && icon && onClose)
                    ? 'cursor-pointer'
                    : undefined,
                `LemonTag--${type}`,
                weight && `LemonTag--${weight}`,
                closeOnClick && 'LemonTag--close-on-click',
                className
            )}
            role={props.onClick || (closeOnClick && icon && onClose) ? 'button' : undefined}
            title={disabledReason || undefined}
            aria-disabled={disabledReason ? true : undefined}
            {...props}
            onClick={
                closeOnClick && icon && onClose
                    ? (e) => {
                          e.stopPropagation()
                          onClose()
                      }
                    : props.onClick
            }
        >
            {icon && closeOnClick && onClose ? (
                <span className="LemonTag__icon-container">
                    <span className="LemonTag__icon LemonTag__icon--default">{icon}</span>
                    <span className="LemonTag__icon-close LemonTag__icon--hover">
                        <IconX className="h-3.5 w-3.5" />
                    </span>
                </span>
            ) : (
                icon && <span className="LemonTag__icon">{icon}</span>
            )}
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
            {closable && !(closeOnClick && icon && onClose) && (
                <LemonButton
                    icon={<IconX className="h-3.5 w-3.5" />}
                    onClick={onClose}
                    size="xsmall"
                    className="LemonTag__right-button"
                />
            )}
        </div>
    )
})
