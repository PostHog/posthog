import React, { HTMLProps } from 'react'
import { copyToClipboard } from 'lib/utils'
import { Tooltip } from 'lib/components/Tooltip'
import { IconCopy } from './icons'
import { LemonButton } from './LemonButton'

interface InlineProps extends HTMLProps<HTMLSpanElement> {
    children?: JSX.Element | string
    explicitValue?: string
    description?: string
    /** Makes text selectable instead of copying on click anywhere */
    selectable?: boolean
    isValueSensitive?: boolean
    tooltipMessage?: string | null
    iconStyle?: Record<string, string | number>
    iconPosition?: 'end' | 'start'
    style?: React.CSSProperties
}

export function CopyToClipboardInline({
    children,
    explicitValue,
    description,
    selectable = false,
    isValueSensitive = false,
    tooltipMessage = null,
    iconStyle = {},
    iconPosition = 'end',
    style,
    ...props
}: InlineProps): JSX.Element {
    const copy = (): boolean => copyToClipboard(explicitValue ?? (children ? children.toString() : ''), description)

    const content = (
        <span
            className={isValueSensitive ? 'ph-no-capture' : ''}
            style={{
                cursor: selectable ? 'text' : 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                flexDirection: iconPosition === 'end' ? 'row' : 'row-reverse',
                flexWrap: 'nowrap',
                width: 'fit-content',
                wordBreak: 'break-all',
                ...style,
            }}
            onClick={!selectable ? copy : undefined}
            {...props}
        >
            <span style={iconPosition === 'start' ? { flexGrow: 1 } : {}}>{children}</span>
            <LemonButton
                size="small"
                icon={<IconCopy />}
                noPadding
                className="copy-icon"
                onClick={!selectable ? undefined : copy}
                style={{
                    [iconPosition === 'end' ? 'marginLeft' : 'marginRight']: 4,
                    ...iconStyle,
                }}
            />
        </span>
    )
    return !selectable || tooltipMessage !== null ? (
        <Tooltip title={tooltipMessage || 'Click to copy'}>{content}</Tooltip>
    ) : (
        <>{content}</>
    )
}
