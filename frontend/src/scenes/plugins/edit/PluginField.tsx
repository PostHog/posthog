import { IconPencil } from '@posthog/icons'
import { LemonButton, LemonFileInput, LemonInput, LemonSelect } from '@posthog/lemon-ui'
import { PluginConfigSchema } from '@posthog/plugin-scaffold/src/types'
import { CodeEditor } from 'lib/components/CodeEditors'
import { useState } from 'react'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { SECRET_FIELD_VALUE } from 'scenes/pipeline/configUtils'

function JsonConfigField(props: {
    onChange?: (value: any) => void
    className: string
    autoFocus: boolean
    value: any
}): JSX.Element {
    return (
        <AutoSizer disableWidth className="min-h-60">
            {({ height }) => (
                <CodeEditor
                    className="border"
                    language="json"
                    value={props.value}
                    onChange={(v) => props.onChange?.(v ?? '')}
                    height={height}
                    options={{
                        minimap: {
                            enabled: false,
                        },
                    }}
                />
            )}
        </AutoSizer>
    )
}

export function PluginField({
    value,
    onChange,
    fieldConfig,
    disabled,
}: {
    value?: any
    onChange?: (value: any) => void
    fieldConfig: PluginConfigSchema
    disabled?: boolean
}): JSX.Element {
    const [editingSecret, setEditingSecret] = useState(false)
    if (
        fieldConfig.secret &&
        !editingSecret &&
        value &&
        (value === SECRET_FIELD_VALUE || value.name === SECRET_FIELD_VALUE)
    ) {
        return (
            <LemonButton
                type="secondary"
                icon={<IconPencil />}
                onClick={() => {
                    onChange?.(fieldConfig.default || '')
                    setEditingSecret(true)
                }}
                disabled={disabled}
            >
                Reset secret {fieldConfig.type === 'attachment' ? 'attachment' : 'field'}
            </LemonButton>
        )
    }

    return fieldConfig.type === 'attachment' ? (
        <>
            {value?.name ? <span>Selected file: {value.name}</span> : null}
            <LemonFileInput
                accept="*"
                multiple={false}
                onChange={(files) => onChange?.(files[0])}
                value={value?.size ? [value] : []}
                showUploadedFiles={false}
            />
        </>
    ) : fieldConfig.type === 'string' ? (
        <LemonInput
            value={value}
            onChange={onChange}
            autoFocus={editingSecret}
            className="ph-no-capture"
            disabled={disabled}
        />
    ) : fieldConfig.type === 'json' ? (
        <JsonConfigField value={value} onChange={onChange} autoFocus={editingSecret} className="ph-no-capture" />
    ) : fieldConfig.type === 'choice' ? (
        <LemonSelect
            fullWidth
            value={value}
            className="ph-no-capture"
            onChange={onChange}
            options={fieldConfig.choices.map((choice) => {
                return { label: choice, value: choice }
            })}
            disabled={disabled}
        />
    ) : (
        <strong className="text-danger">
            Unknown field type "<code>{fieldConfig.type}</code>".
            <br />
            You may need to upgrade PostHog!
        </strong>
    )
}
