import React from 'react'
import { twMerge } from 'tailwind-merge'

interface MessageTemplateProps {
    type: 'human' | 'ai'
    action?: React.ReactNode
    className?: string
    boxClassName?: string
    wrapperClassName?: string
    children?: React.ReactNode
    header?: React.ReactNode
}

export const MessageTemplate = React.forwardRef<HTMLDivElement, MessageTemplateProps>(function MessageTemplate(
    { type, children, className, boxClassName, wrapperClassName, action, header },
    ref
) {
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
                            'py-2 px-3',
                            type === 'human' && 'font-medium border rounded-lg bg-surface-primary',
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
})
