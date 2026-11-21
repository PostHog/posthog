import React from 'react'

import { IconCopy } from '@posthog/icons'
import { Button, cn } from '@posthog/quill'

export interface QuillCopyToClipboardInlineProps {
    children?: React.ReactNode
    onCopy: () => void
    /** Makes the text selectable, so only the icon copies. */
    selectable: boolean
    isValueSensitive: boolean
    tooltipMessage: React.ReactNode | null
    iconPosition: 'end' | 'start'
    className?: string
    'data-attr'?: string
}

export const QuillCopyToClipboardInline = React.forwardRef<HTMLSpanElement, QuillCopyToClipboardInlineProps>(
    function QuillCopyToClipboardInline(
        {
            children,
            onCopy,
            selectable,
            isValueSensitive,
            tooltipMessage,
            iconPosition,
            className,
            'data-attr': dataAttr,
            ...props
        },
        ref
    ) {
        const tooltip = tooltipMessage || 'Click to copy'

        if (!children) {
            return (
                <Button
                    size="icon-xs"
                    aria-label="Click to copy"
                    tooltip={tooltip}
                    onClick={onCopy}
                    data-attr={dataAttr ?? 'copy-icon'}
                >
                    <IconCopy />
                </Button>
            )
        }

        return (
            <span
                ref={ref}
                className={cn(
                    'inline-flex max-w-full min-w-0 items-center',
                    isValueSensitive && 'ph-no-capture',
                    className
                )}
                data-attr={dataAttr}
                {...props}
            >
                {selectable ? (
                    <span
                        className={cn(
                            'inline-flex min-w-0 items-center gap-1',
                            iconPosition === 'start' && 'flex-row-reverse'
                        )}
                    >
                        <span className="min-w-0 truncate">{children}</span>
                        <Button
                            size="icon-xs"
                            aria-label="Click to copy"
                            tooltip={tooltip}
                            onClick={onCopy}
                            data-attr="copy-icon"
                        >
                            <IconCopy />
                        </Button>
                    </span>
                ) : (
                    <Button size="sm" className="min-w-0" tooltip={tooltip} onClick={onCopy} data-attr="copy-icon">
                        {iconPosition === 'start' && <IconCopy />}
                        <span className="min-w-0 truncate">{children}</span>
                        {iconPosition === 'end' && <IconCopy />}
                    </Button>
                )}
            </span>
        )
    }
)
