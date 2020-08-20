import React, { ReactNode } from 'react'
import { toast } from 'react-toastify'
import { Tooltip, Input } from 'antd'
import { CopyOutlined } from '@ant-design/icons'

interface InlineProps {
    children: ReactNode | string
    explicitValue?: string
    description?: string
    isValueSensitive?: boolean
}

interface InputProps {
    value?: string
    description?: string
    isValueSensitive?: boolean
}

function copyToClipboard(value: string, description?: string): void {
    const descriptionAdjusted = description ? description.trim() + ' ' : ''
    try {
        navigator.clipboard.writeText(value)
        toast.success(`Copied ${descriptionAdjusted}to clipboard!`)
    } catch (e) {
        toast.error(`Could not copy ${descriptionAdjusted}to clipboard: ${e}`)
    }
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
                    copyToClipboard(explicitValue ?? children!.toString(), description)
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
    description,
    isValueSensitive = false,
    ...props
}: InputProps): JSX.Element {
    return (
        <Input
            className={isValueSensitive ? 'ph-no-capture' : undefined}
            type="text"
            value={value}
            suffix={
                <Tooltip title="Copy to Clipboard">
                    <CopyOutlined
                        onClick={() => {
                            copyToClipboard(value, description)
                        }}
                    />
                </Tooltip>
            }
            {...props}
        />
    )
}
