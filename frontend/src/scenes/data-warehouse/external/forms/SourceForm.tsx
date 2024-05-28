import { LemonInput, LemonSelect, LemonSwitch, LemonTextArea } from '@posthog/lemon-ui'
import { Form, Group } from 'kea-forms'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { SourceConfig, SourceFieldConfig } from '~/types'

import { SOURCE_DETAILS, sourceWizardLogic } from '../../new/sourceWizardLogic'

interface SourceFormProps {
    sourceConfig: SourceConfig
}

const sourceFieldToElement = (field: SourceFieldConfig): JSX.Element => {
    if (field.type === 'switch-group') {
        return (
            <LemonField key={field.name} name={[field.name, 'enabled']} label={field.label}>
                {({ value, onChange }) => (
                    <>
                        <LemonSwitch checked={value} onChange={onChange} />
                        {value && <Group name={field.name}>{field.fields.map(sourceFieldToElement)}</Group>}
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
                                ?.fields?.map(sourceFieldToElement)}
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
    return (
        <Form logic={sourceWizardLogic} formKey="sourceConnectionDetails" className="space-y-4" enableFormOnSubmit>
            <Group name="payload">
                {SOURCE_DETAILS[sourceConfig.name].fields.map((field) => sourceFieldToElement(field))}
            </Group>
            <LemonField name="prefix" label="Table Prefix (optional)">
                <LemonInput className="ph-ignore-input" data-attr="prefix" placeholder="internal_" />
            </LemonField>
        </Form>
    )
}
