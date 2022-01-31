import React, { HTMLProps } from 'react'
import { Input } from 'antd'
import { CopyOutlined } from '@ant-design/icons'
import { copyToClipboard } from 'lib/utils'
import { Tooltip } from 'lib/components/Tooltip'
import { IconCopy } from './icons'
import { LemonButton } from './LemonButton'
import clsx from 'clsx'

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

interface InputProps {
    value: string
    placeholder?: string
    description?: string
    isValueSensitive?: boolean
    className?: string
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
                compact
                icon={<IconCopy />}
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

export function CopyToClipboardInput({
    value,
    placeholder,
    description,
    isValueSensitive = false,
    className,
    ...props
}: InputProps): JSX.Element {
    return (
        <Input
            className={clsx(isValueSensitive && 'ph-no-capture', className)}
            type="text"
            value={value}
            placeholder={placeholder || 'nothing to show here'}
            disabled={!value}
            suffix={
                value ? (
                    <Tooltip title="Copy to Clipboard">
                        <CopyOutlined
                            onClick={() => {
                                copyToClipboard(value, description)
                            }}
                        />
                    </Tooltip>
                ) : null
            }
            {...props}
        />
    )
}
