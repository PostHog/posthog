import { LemonInput } from '@posthog/lemon-ui'
import { Form } from 'kea-forms'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { SourceConfig } from '~/types'

import { SOURCE_DETAILS, sourceWizardLogic } from '../../new/sourceWizardLogic'

interface SourceFormProps {
    sourceConfig: SourceConfig
}

export default function SourceForm({ sourceConfig }: SourceFormProps): JSX.Element {
    return (
        <Form logic={sourceWizardLogic} formKey="sourceConnectionDetails" className="space-y-4" enableFormOnSubmit>
            {SOURCE_DETAILS[sourceConfig.name].fields.map((field) => (
                <LemonField key={field.name} name={['payload', field.name]} label={field.label}>
                    <LemonInput
                        className="ph-ignore-input"
                        data-attr={field.name}
                        placeholder={field.placeholder}
                        type={field.type}
                    />
                </LemonField>
            ))}
            <LemonField name="prefix" label="Table Prefix (optional)">
                <LemonInput className="ph-ignore-input" data-attr="prefix" placeholder="internal_" />
            </LemonField>
        </Form>
    )
}
