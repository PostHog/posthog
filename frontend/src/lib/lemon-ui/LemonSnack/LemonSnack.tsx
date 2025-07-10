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
                    'text-primary-alt inline-flex max-w-full items-center overflow-hidden break-all py-1 leading-5',
                    !wrap && 'whitespace-nowrap',
                    isRegular
                        ? 'bg-accent-highlight-secondary rounded px-1.5'
                        : 'bg-primary-alt-highlight h-8 rounded-full px-4',
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
                    <span className={clsx('LemonSnack__close ml-1 shrink-0', isRegular || '-mr-1')}>
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
