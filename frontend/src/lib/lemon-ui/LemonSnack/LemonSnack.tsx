import clsx from 'clsx'
import React, { forwardRef } from 'react'
import { twMerge } from 'tailwind-merge'

import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

export interface LemonSnackProps {
    type?: 'regular' | 'pill'
    children?: React.ReactNode
    onClick?: React.MouseEventHandler
    onClose?: React.MouseEventHandler
    title?: string
    wrap?: boolean
    className?: string
    'data-attr'?: string
}

export const LemonSnack: React.FunctionComponent<LemonSnackProps & React.RefAttributes<HTMLSpanElement>> = forwardRef(
    function LemonSnack({ type = 'regular', children, wrap, onClick, onClose, title, className }, ref): JSX.Element {
        const isRegular = type === 'regular'
        const isClickable = !!onClick
        return (
            <span
                ref={ref}
                className={twMerge(
                    'inline-flex text-primary-alt max-w-full overflow-hidden break-all items-center py-1 leading-5',
                    !wrap && 'whitespace-nowrap',
                    isRegular
                        ? 'bg-accent-highlight-secondary px-1.5 rounded'
                        : 'bg-primary-alt-highlight px-4 rounded-full h-8',
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
                            onClick={(e) => {
                                e.stopPropagation()
                                onClose(e)
                            }}
                        />
                    </span>
                )}
            </span>
        )
    }
)
