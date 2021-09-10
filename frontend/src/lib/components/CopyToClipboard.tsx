import React, { HTMLProps } from 'react'
import { Input } from 'antd'
import { CopyOutlined } from '@ant-design/icons'
import { copyToClipboard } from 'lib/utils'
import { Tooltip } from 'lib/components/Tooltip'

interface InlineProps extends HTMLProps<HTMLSpanElement> {
    children?: JSX.Element | string
    explicitValue?: string
    description?: string
    isValueSensitive?: boolean
    tooltipMessage?: string
    iconStyle?: Record<string, string | number>
    iconPosition?: 'end' | 'start'
}

interface InputProps {
    value: string
    placeholder?: string
    description?: string
    isValueSensitive?: boolean
}

export function CopyToClipboardInline({
    children,
    explicitValue,
    description,
    isValueSensitive = false,
    tooltipMessage = 'Click to copy',
    iconStyle = {},
    iconPosition = 'end',
    ...props
}: InlineProps): JSX.Element {
    return (
        <Tooltip title={tooltipMessage}>
            <span
                className={isValueSensitive ? 'ph-no-capture' : ''}
                style={{
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'flex-end',
                    flexDirection: iconPosition === 'end' ? 'row' : 'row-reverse',
                    flexWrap: iconPosition === 'end' ? 'wrap' : 'wrap-reverse',
                }}
                onClick={() => {
                    copyToClipboard(explicitValue ?? (children ? children.toString() : ''), description)
                }}
                {...props}
            >
                <span style={iconPosition === 'start' ? { flexGrow: 1 } : {}}>{children}</span>
                <CopyOutlined
                    style={iconPosition === 'end' ? { marginLeft: 4, ...iconStyle } : { marginRight: 4, ...iconStyle }}
                />
            </span>
        </Tooltip>
    )
}

export function CopyToClipboardInput({
    value,
    placeholder,
    description,
    isValueSensitive = false,
    ...props
}: InputProps): JSX.Element {
    return (
        <Input
            className={isValueSensitive ? 'ph-no-capture' : ''}
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
