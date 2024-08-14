import { LemonInput, LemonSelect, LemonSwitch, LemonTextArea } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { Form, Group } from 'kea-forms'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { SourceConfig, SourceFieldConfig } from '~/types'

import { SOURCE_DETAILS, sourceWizardLogic } from '../../new/sourceWizardLogic'
import { DataWarehouseIntegrationChoice } from './DataWarehouseIntegrationChoice'

interface SourceFormProps {
    sourceConfig: SourceConfig
    showPrefix?: boolean
    showSourceFields?: boolean
}

const sourceFieldToElement = (field: SourceFieldConfig, sourceConfig: SourceConfig): JSX.Element => {
    if (field.type === 'switch-group') {
        return (
            <LemonField key={field.name} name={[field.name, 'enabled']} label={field.label}>
                {({ value, onChange }) => (
                    <>
                        <LemonSwitch checked={value} onChange={onChange} />
                        {value && (
                            <Group name={field.name}>
                                {field.fields.map((field) => sourceFieldToElement(field, sourceConfig))}
                            </Group>
                        )}
                    </>
                )}
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
                        <LemonSelect options={field.options} value={value ?? field.defaultValue} onChange={onChange} />
                        <Group name={field.name}>
                            {field.options
                                .find((n) => n.value === (value ?? field.defaultValue))
                                ?.fields?.map((field) => sourceFieldToElement(field, sourceConfig))}
                        </Group>
                    </>
                )}
            </LemonField>
        )
    }

    if (field.type === 'textarea') {
        return (
            <LemonField key={field.name} name={field.name} label={field.label}>
                <LemonTextArea
                    className="ph-ignore-input"
                    data-attr={field.name}
                    placeholder={field.placeholder}
                    minRows={4}
                />
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

    return (
        <LemonField key={field.name} name={field.name} label={field.label}>
            <LemonInput
                className="ph-ignore-input"
                data-attr={field.name}
                placeholder={field.placeholder}
                type={field.type}
            />
        </LemonField>
    )
}

export default function SourceForm({ sourceConfig }: SourceFormProps): JSX.Element {
    const { source } = useValues(sourceWizardLogic)
    const showSourceFields = SOURCE_DETAILS[sourceConfig.name].showSourceForm
        ? SOURCE_DETAILS[sourceConfig.name].showSourceForm?.(source.payload)
        : true
    const showPrefix = SOURCE_DETAILS[sourceConfig.name].showPrefix
        ? SOURCE_DETAILS[sourceConfig.name].showPrefix?.(source.payload)
        : true

    return (
        <Form logic={sourceWizardLogic} formKey="sourceConnectionDetails" className="space-y-4" enableFormOnSubmit>
            {showSourceFields && (
                <Group name="payload">
                    {SOURCE_DETAILS[sourceConfig.name].fields.map((field) => sourceFieldToElement(field, sourceConfig))}
                </Group>
            )}
            {showPrefix && (
                <LemonField name="prefix" label="Table Prefix (optional)">
                    <LemonInput className="ph-ignore-input" data-attr="prefix" placeholder="internal_" />
                </LemonField>
            )}
        </Form>
    )
}
