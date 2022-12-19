import { LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { IconClose } from '../icons'
import './LemonSnack.scss'

export interface LemonSnackProps {
    children?: React.ReactNode
    onClose?: () => void
    title?: string
    wrap?: boolean
    className?: string
    'data-attr'?: string
    color?: 'primary-extralight' | 'primary-highlight'
}

export function LemonSnack({
    children,
    wrap,
    onClose,
    title,
    className,
    color = 'primary-highlight',
}: LemonSnackProps): JSX.Element {
    return (
        <span
            className={clsx(`LemonSnack bg-${color}`, className, {
                'LemonSnack--wrap': wrap,
            })}
        >
            <span className="LemonSnack__inner" title={title ?? (typeof children === 'string' ? children : undefined)}>
                {children}
            </span>

            {onClose ? (
                <span className="LemonSnack__close">
                    <LemonButton status="stealth" size="small" noPadding icon={<IconClose />} onClick={onClose} />
                </span>
            ) : undefined}
        </span>
    )
}
