import { LemonDivider, LemonFileInput, LemonInput, LemonSelect, LemonSwitch, LemonTextArea } from '@posthog/lemon-ui'
import { FieldName, Form, Group } from 'kea-forms'
import { LemonField } from 'lib/lemon-ui/LemonField'
import React, { useEffect } from 'react'

import { SourceConfig, SourceFieldConfig } from '~/types'

import { SOURCE_DETAILS, sourceWizardLogic } from '../../new/sourceWizardLogic'
import { DataWarehouseIntegrationChoice } from './DataWarehouseIntegrationChoice'
import { parseConnectionString } from './parseConnectionString'

export interface SourceFormProps {
    sourceConfig: SourceConfig
    showPrefix?: boolean
    jobInputs?: Record<string, any>
    setSourceConfigValue?: (key: FieldName, value: any) => void
}

const CONNECTION_STRING_DEFAULT_PORT = {
    Postgres: 5432,
}

const sourceFieldToElement = (
    field: SourceFieldConfig,
    sourceConfig: SourceConfig,
    lastValue?: any,
    isUpdateMode?: boolean
): JSX.Element => {
    // It doesn't make sense for this to show on an update to an existing connection since we likely just want to change
    // a field or two. There is also some divergence in creates vs. updates that make this a bit more complex to handle.
    if (field.type === 'text' && field.name === 'connection_string') {
        if (isUpdateMode) {
            return <React.Fragment key={field.name} />
        }
        return (
            <React.Fragment key={field.name}>
                <LemonField name={field.name} label={field.label}>
                    {({ onChange }) => (
                        <LemonInput
                            key={field.name}
                            className="ph-connection-string"
                            data-attr={field.name}
                            placeholder={field.placeholder}
                            type="text"
                            onChange={(updatedConnectionString) => {
                                onChange(updatedConnectionString)
                                const { host, port, database, user, password, isValid } =
                                    parseConnectionString(updatedConnectionString)

                                if (isValid) {
                                    sourceWizardLogic.actions.setSourceConnectionDetailsValue(
                                        ['payload', 'database'],
                                        database || ''
                                    )
                                    sourceWizardLogic.actions.setSourceConnectionDetailsValue(
                                        ['payload', 'host'],
                                        host || ''
                                    )
                                    sourceWizardLogic.actions.setSourceConnectionDetailsValue(
                                        ['payload', 'user'],
                                        user || ''
                                    )
                                    sourceWizardLogic.actions.setSourceConnectionDetailsValue(
                                        ['payload', 'port'],
                                        port || CONNECTION_STRING_DEFAULT_PORT[sourceConfig.name]
                                    )
                                    sourceWizardLogic.actions.setSourceConnectionDetailsValue(
                                        ['payload', 'password'],
                                        password || ''
                                    )
                                }
                            }}
                        />
                    )}
                </LemonField>
                <LemonDivider />
            </React.Fragment>
        )
    }

    if (field.type === 'switch-group') {
        const enabled = !!lastValue?.[field.name]?.enabled || lastValue?.[field.name]?.enabled === 'True'
        return (
            <LemonField key={field.name} name={[field.name, 'enabled']} label={field.label}>
                {({ value, onChange }) => {
                    const isEnabled = value === undefined || value === null || value === 'False' ? enabled : value
                    return (
                        <>
                            {!!field.caption && <p className="mb-0">{field.caption}</p>}
                            <LemonSwitch checked={isEnabled} onChange={onChange} />
                            {isEnabled && (
                                <Group name={field.name}>
                                    {field.fields.map((field) =>
                                        sourceFieldToElement(field, sourceConfig, lastValue?.[field.name])
                                    )}
                                </Group>
                            )}
                        </>
                    )
                }}
            </LemonField>
        )
    }

    if (field.type === 'select') {
        const hasOptionFields = !!field.options.filter((n) => (n.fields?.length ?? 0) > 0).length

        return (
            <LemonField
                key={field.name}
                name={hasOptionFields ? [field.name, 'selection'] : field.name}
                label={field.label}
            >
                {({ value, onChange }) => (
                    <>
                        <LemonSelect
                            options={field.options}
                            value={
                                value === undefined || value === null
                                    ? lastValue?.[field.name]
                                    : value || field.defaultValue
                            }
                            onChange={onChange}
                        />
                        <Group name={field.name}>
                            {field.options
                                .find((n) => n.value === (value ?? field.defaultValue))
                                ?.fields?.map((field) =>
                                    sourceFieldToElement(field, sourceConfig, lastValue?.[field.name])
                                )}
                        </Group>
                    </>
                )}
            </LemonField>
        )
    }

    if (field.type === 'textarea') {
        return (
            <LemonField key={field.name} name={field.name} label={field.label}>
                {({ value, onChange }) => (
                    <LemonTextArea
                        className="ph-ignore-input"
                        data-attr={field.name}
                        placeholder={field.placeholder}
                        minRows={4}
                        value={value || ''}
                        onChange={onChange}
                    />
                )}
            </LemonField>
        )
    }

    if (field.type === 'oauth') {
        return (
            <LemonField key={field.name} name={field.name} label={field.label}>
                {({ value, onChange }) => (
                    <DataWarehouseIntegrationChoice
                        key={field.name}
                        sourceConfig={sourceConfig}
                        value={value}
                        onChange={onChange}
                    />
                )}
            </LemonField>
        )
    }

    if (field.type === 'file-upload') {
        return (
            <LemonField key={field.name} name={field.name} label={field.label}>
                {({ value, onChange }) => (
                    <div className="bg-[white] p-2 border rounded-[var(--radius)]">
                        <LemonFileInput value={value} accept={field.fileFormat} multiple={false} onChange={onChange} />
                    </div>
                )}
            </LemonField>
        )
    }

    return (
        <LemonField key={field.name} name={field.name} label={field.label}>
            {({ value, onChange }) => (
                <LemonInput
                    className="ph-ignore-input"
                    data-attr={field.name}
                    placeholder={field.placeholder}
                    type={field.type as 'text'}
                    value={value || ''}
                    onChange={onChange}
                />
            )}
        </LemonField>
    )
}

export default function SourceFormContainer(props: SourceFormProps): JSX.Element {
    return (
        <Form logic={sourceWizardLogic} formKey="sourceConnectionDetails" enableFormOnSubmit>
            <SourceFormComponent {...props} />
        </Form>
    )
}

export function SourceFormComponent({
    sourceConfig,
    showPrefix = true,
    jobInputs,
    setSourceConfigValue,
}: SourceFormProps): JSX.Element {
    useEffect(() => {
        if (jobInputs && setSourceConfigValue) {
            for (const input of Object.keys(jobInputs || {})) {
                setSourceConfigValue(['payload', input], jobInputs[input])
            }
        }
    }, [JSON.stringify(jobInputs), setSourceConfigValue])

    const isUpdateMode = !!setSourceConfigValue

    return (
        <div className="deprecated-space-y-4">
            <Group name="payload">
                {SOURCE_DETAILS[sourceConfig.name].fields.map((field) =>
                    sourceFieldToElement(field, sourceConfig, jobInputs?.[field.name], isUpdateMode)
                )}
            </Group>
            {showPrefix && (
                <LemonField name="prefix" label="Table prefix (optional)">
                    {({ value, onChange }) => {
                        const tableName = value
                            ? `${sourceConfig.name.toLowerCase()}.${value}.table_name`
                            : `${sourceConfig.name.toLowerCase()}.table_name`
                        return (
                            <>
                                <LemonInput
                                    className="ph-ignore-input"
                                    data-attr="prefix"
                                    placeholder="internal"
                                    value={value}
                                    onChange={onChange}
                                />
                                <p>
                                    Example table name:&nbsp;
                                    <strong>{tableName}</strong>
                                </p>
                            </>
                        )
                    }}
                </LemonField>
            )}
        </div>
    )
}
