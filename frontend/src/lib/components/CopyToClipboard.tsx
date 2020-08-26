import React from 'react'
import { Tooltip, Input } from 'antd'
import { CopyOutlined } from '@ant-design/icons'
import { copyToClipboard } from 'lib/utils'

interface InlineProps {
    children: JSX.Element | string
    explicitValue?: string
    description?: string
    isValueSensitive?: boolean
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
    ...props
}: InlineProps): JSX.Element {
    return (
        <Tooltip title="Click to copy">
            <span
                className={isValueSensitive ? 'ph-no-capture' : undefined}
                style={{ cursor: 'pointer' }}
                onClick={() => {
                    copyToClipboard(explicitValue ?? children.toString(), description)
                }}
                {...props}
            >
                {children}
                <CopyOutlined style={{ marginLeft: 4 }} />
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
            className={isValueSensitive ? 'ph-no-capture' : undefined}
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
