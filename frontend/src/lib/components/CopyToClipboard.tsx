import clsx from 'clsx'
import React from 'react'

import { IconCopy } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

interface InlinePropsBase {
    description?: string
    /** Makes text selectable instead of copying on click anywhere */
    selectable?: boolean
    /** adds ph-no-capture class to the element **/
    isValueSensitive?: boolean
    tooltipMessage?: React.ReactNode | null
    iconStyle?: Record<string, string | number>
    /** @default end */
    iconPosition?: 'end' | 'start'
    /** @default small */
    iconSize?: 'small' | 'xsmall'
    className?: string
    /** @deprecated */
    style?: React.CSSProperties
    /** @default true */
    iconMargin?: boolean
}
interface InlinePropsWithStringInside extends InlinePropsBase {
    children: string
    explicitValue?: string
}
interface InlinePropsWithJSXInside extends InlinePropsBase {
    children?: JSX.Element
    explicitValue: string
}
type InlineProps = InlinePropsWithStringInside | InlinePropsWithJSXInside

export const CopyToClipboardInline = React.forwardRef<HTMLSpanElement, InlineProps>(function CopyToClipboardInline(
    {
        children,
        explicitValue,
        description,
        selectable = false,
        isValueSensitive = false,
        tooltipMessage = null,
        iconStyle,
        iconPosition = 'end',
        iconSize = 'small',
        className,
        style,
        iconMargin = true,
        ...props
    },
    ref
) {
    const copy = (): void => void copyToClipboard((explicitValue ?? children) as string, description)

    let content = (
        <LemonButton
            size={iconSize}
            icon={<IconCopy style={{ ...iconStyle }} />}
            noPadding
            className={iconMargin ? 'ml-1' : undefined}
            data-attr="copy-icon"
            onClick={selectable || !children ? copy : undefined}
        />
    )

    if (children) {
        content = (
            <span
                className={clsx(
                    'relative truncate inline-flex items-center flex-nowrap w-fit break-all',
                    selectable ? 'cursor-text' : 'cursor-pointer',
                    iconPosition === 'end' ? 'flex-row' : 'flex-row-reverse',
                    isValueSensitive && 'ph-no-capture',
                    className
                )}
                // eslint-disable-next-line react/forbid-dom-props
                style={style}
                onClick={!selectable ? copy : undefined}
                {...props}
                ref={ref}
            >
                <span className={iconPosition === 'start' ? 'grow-1' : undefined}>{children}</span>
                {content}
            </span>
        )
    }
    return !selectable || tooltipMessage !== null ? (
        <Tooltip title={tooltipMessage || 'Click to copy'}>{content}</Tooltip>
    ) : (
        <>{content}</>
    )
})
