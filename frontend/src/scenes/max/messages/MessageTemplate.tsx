import * as React from 'react'
import { twMerge } from 'tailwind-merge'

interface MessageTemplateProps {
    type: 'human' | 'ai'
    action?: React.ReactNode
    className?: string
    boxClassName?: string
    wrapperClassName?: string
    ref?: React.RefObject<HTMLDivElement>
    children?: React.ReactNode
    header?: React.ReactNode
}

export function MessageTemplate({
    ref,
    type,
    children,
    className,
    boxClassName,
    wrapperClassName,
    action,
    header,
}: MessageTemplateProps): JSX.Element {
    return (
        <div
            className={twMerge(
                'flex flex-col gap-px w-full break-words scroll-mt-12',
                type === 'human' ? 'items-end' : 'items-start',
                className
            )}
            ref={ref}
            data-message-type={type}
        >
            <div className={twMerge('max-w-full', wrapperClassName)}>
                {header}
                {children && (
                    <div
                        className={twMerge(
                            'border py-2 px-3 rounded-lg bg-surface-primary',
                            type === 'human' && 'font-medium',
                            boxClassName
                        )}
                    >
                        {children}
                    </div>
                )}
            </div>
            {action}
        </div>
    )
}
