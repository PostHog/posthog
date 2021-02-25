import { UploadField } from 'scenes/plugins/edit/UploadField'
import { Button, Input, Select } from 'antd'
import React, { useState } from 'react'
import { PluginConfigSchema } from '@posthog/plugin-scaffold/src/types'

export function PluginField({
    value,
    onChange,
    fieldConfig,
}: {
    value?: any
    onChange?: (value: any) => void
    fieldConfig: PluginConfigSchema
}): JSX.Element {
    const [editingSecret, setEditingSecret] = useState(false)
    if (fieldConfig.secret && !editingSecret && value) {
        return (
            <Button
                onClick={() => {
                    setEditingSecret(true)
                    onChange?.('')
                }}
            >
                Edit secret {fieldConfig.type === 'attachment' ? 'attachment' : 'field'}
            </Button>
        )
    }

    return fieldConfig.type === 'attachment' ? (
        <UploadField value={value} onChange={onChange} />
    ) : fieldConfig.type === 'string' ? (
        <Input value={value} onChange={onChange} autoFocus={editingSecret} />
    ) : fieldConfig.type === 'choice' ? (
        <Select dropdownMatchSelectWidth={false} value={value} onChange={onChange}>
            {fieldConfig.choices.map((choice) => (
                <Select.Option value={choice} key={choice}>
                    {choice}
                </Select.Option>
            ))}
        </Select>
    ) : (
        <strong style={{ color: 'var(--danger)' }}>
            Unknown field type "<code>{fieldConfig.type}</code>".
            <br />
            You may need to upgrade PostHog!
        </strong>
    )
}
