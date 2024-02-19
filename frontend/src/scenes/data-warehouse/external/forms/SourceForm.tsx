import { LemonInput } from '@posthog/lemon-ui'
import { Form } from 'kea-forms'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { ExternalDataSourceType } from '~/types'

import { SOURCE_DETAILS } from '../sourceModalLogic'
import { sourceFormLogic } from './sourceFormLogic'

interface SourceFormProps {
    sourceType: ExternalDataSourceType
}

export default function SourceForm({ sourceType }: SourceFormProps): JSX.Element {
    return (
        <Form
            logic={sourceFormLogic}
            props={{ sourceType }}
            formKey={sourceType == 'Postgres' ? 'databaseSchemaForm' : 'externalDataSource'}
            className="space-y-4"
            enableFormOnSubmit
        >
            {SOURCE_DETAILS[sourceType].fields.map((field) => (
                <LemonField key={field.name} name={['payload', field.name]} label={field.label}>
                    <LemonInput className="ph-ignore-input" data-attr={field.name} />
                </LemonField>
            ))}
            <LemonField name="prefix" label="Table Prefix (optional)">
                <LemonInput className="ph-ignore-input" data-attr="prefix" placeholder="internal_" />
            </LemonField>
        </Form>
    )
}
