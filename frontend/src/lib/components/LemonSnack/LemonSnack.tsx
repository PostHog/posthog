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
            className={clsx(
                'LemonSnack',
                `inline-flex rounded text-primary-alt max-w-full overflow-hidden break-all items-center px-1.5 py-1 bg-${color}`,
                !wrap && 'whitespace-nowrap',
                className
            )}
        >
            <span
                className="overflow-hidden text-ellipsis"
                title={title ?? (typeof children === 'string' ? children : undefined)}
            >
                {children}
            </span>

            {onClose && (
                <span className="LemonSnack__close ml-1 shrink-0">
                    <LemonButton status="stealth" size="small" noPadding icon={<IconClose />} onClick={onClose} />
                </span>
            )}
        </span>
    )
}
