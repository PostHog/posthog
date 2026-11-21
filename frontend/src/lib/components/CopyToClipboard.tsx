import clsx from 'clsx'
import React, { Suspense, lazy } from 'react'

import { IconCopy } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { useQuillSurface } from 'lib/ui/QuillSurface/quillSurfaceContext'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { retryImport } from 'lib/utils/retryImport'

// This file ships on every logged-in page, and quill must load only where a page turns it on.
const QuillCopyToClipboardInline = lazy(() =>
    retryImport(() => import('./QuillCopyToClipboardInline')).then((m) => ({ default: m.QuillCopyToClipboardInline }))
)

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
    'data-attr'?: string
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
        'data-attr': dataAttr,
        ...props
    },
    ref
) {
    const quillSurface = useQuillSurface()
    const copy = (): void => void copyToClipboard((explicitValue ?? children) as string, description)

    if (quillSurface) {
        return (
            <Suspense fallback={null}>
                <QuillCopyToClipboardInline
                    ref={ref}
                    onCopy={copy}
                    selectable={selectable}
                    isValueSensitive={isValueSensitive}
                    tooltipMessage={tooltipMessage}
                    iconPosition={iconPosition}
                    className={className}
                    data-attr={dataAttr}
                    {...props}
                >
                    {children}
                </QuillCopyToClipboardInline>
            </Suspense>
        )
    }

    let content = (
        <LemonButton
            size={iconSize}
            icon={<IconCopy style={{ ...iconStyle }} />}
            noPadding
            className={iconMargin ? 'ml-1' : undefined}
            data-attr={!children && dataAttr ? dataAttr : 'copy-icon'}
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
                data-attr={dataAttr}
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
