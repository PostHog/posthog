import clsx from 'clsx'
import React, { useEffect, useRef, useState } from 'react'

import { IconCheck, IconCopy } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

// How long the copy icon stays a checkmark after a successful copy.
const COPIED_RESET_MS = 1700

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
export type InlineProps = InlinePropsWithStringInside | InlinePropsWithJSXInside

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
    const [copied, setCopied] = useState(false)
    const copiedResetRef = useRef<number | undefined>(undefined)

    useEffect(() => () => window.clearTimeout(copiedResetRef.current), [])

    const copy = (): void => {
        void copyToClipboard((explicitValue ?? children) as string, description).then((didCopy) => {
            if (didCopy) {
                setCopied(true)
                window.clearTimeout(copiedResetRef.current)
                copiedResetRef.current = window.setTimeout(() => setCopied(false), COPIED_RESET_MS)
            }
        })
    }

    const copyLabel = `Copy ${description ?? 'text'}`

    let content = (
        <LemonButton
            size={iconSize}
            icon={copied ? <IconCheck style={{ ...iconStyle }} /> : <IconCopy style={{ ...iconStyle }} />}
            noPadding
            // When there's no text to click, padding plus a matching negative margin widens the
            // click target without shifting layout, so the icon-only button (e.g. in a zero-width
            // table column) stops being a near-impossible target.
            className={clsx(
                !children && 'p-1 -m-1',
                iconMargin && 'ml-1',
                copied && '[--lemon-button-color:var(--success)]'
            )}
            data-attr="copy-icon"
            aria-label={copyLabel}
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
    // Selectable text can't advertise "Click to copy" (clicking selects), so it drops the tooltip —
    // but an icon-only button always copies on click, so it keeps one regardless of `selectable`.
    const showTooltip = !selectable || tooltipMessage !== null || !children

    return (
        <>
            {showTooltip ? (
                <Tooltip title={tooltipMessage || (copied ? 'Copied!' : 'Click to copy')}>{content}</Tooltip>
            ) : (
                content
            )}
            <span aria-live="polite" aria-atomic="true" className="sr-only">
                {copied ? `Copied ${description ?? 'text'} to clipboard` : ''}
            </span>
        </>
    )
})
