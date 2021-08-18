import { UploadField } from 'scenes/plugins/edit/UploadField'
import { Button, Input, Select } from 'antd'
import React, { useState } from 'react'
import { PluginConfigSchema } from '@posthog/plugin-scaffold/src/types'
import { EditOutlined } from '@ant-design/icons'
import { SECRET_FIELD_VALUE } from 'scenes/plugins/utils'

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
    if (
        fieldConfig.secret &&
        !editingSecret &&
        value &&
        (value === SECRET_FIELD_VALUE || value.name === SECRET_FIELD_VALUE)
    ) {
        return (
            <Button
                icon={<EditOutlined />}
                onClick={() => {
                    onChange?.(fieldConfig.default || '')
                    setEditingSecret(true)
                }}
            >
                Reset secret {fieldConfig.type === 'attachment' ? 'attachment' : 'field'}
            </Button>
        )
    }

    return fieldConfig.type === 'attachment' ? (
        <UploadField value={value} onChange={onChange} />
    ) : fieldConfig.type === 'string' ? (
        <Input value={value} onChange={onChange} autoFocus={editingSecret} className="ph-ignore-input" />
    ) : fieldConfig.type === 'choice' ? (
        <Select dropdownMatchSelectWidth={false} value={value} onChange={onChange} showSearch>
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
