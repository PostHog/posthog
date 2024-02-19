import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { forwardRef } from 'react'

export interface LemonSnackProps {
    type?: 'regular' | 'pill'
    children?: React.ReactNode
    onClick?: () => void
    onClose?: () => void
    title?: string
    wrap?: boolean
    className?: string
    'data-attr'?: string
}

export const LemonSnack: React.FunctionComponent<LemonSnackProps & React.RefAttributes<HTMLSpanElement>> = forwardRef(
    function LemonSnack({ type = 'regular', children, wrap, onClick, onClose, title, className }, ref): JSX.Element {
        const isRegular = type === 'regular'
        const isClickable = !!onClick
        const bgColor = isRegular ? 'primary-highlight' : 'primary-alt-highlight'
        return (
            <span
                ref={ref}
                className={clsx(
                    'LemonSnack',
                    !isRegular && 'LemonSnack--pill',
                    `inline-flex text-primary-alt max-w-full overflow-hidden break-all items-center py-1 bg-${bgColor}`,
                    !wrap && 'whitespace-nowrap',
                    isRegular ? 'px-1.5 rounded' : 'px-4 rounded-full h-8',
                    isClickable && 'cursor-pointer',
                    className
                )}
                onClick={onClick}
            >
                <span
                    className="overflow-hidden text-ellipsis"
                    title={title ?? (typeof children === 'string' ? children : undefined)}
                >
                    {children}
                </span>

                {onClose && (
                    <span className={clsx('LemonSnack__close shrink-0 ml-1', isRegular || '-mr-1')}>
                        <LemonButton
                            size="small"
                            noPadding
                            icon={<IconX />}
                            onClick={(event) => {
                                event.stopPropagation()
                                onClose()
                            }}
                        />
                    </span>
                )}
            </span>
        )
    }
)
