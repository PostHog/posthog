import { LemonInput, LemonSelect } from '@posthog/lemon-ui'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'

import { dataWarehouseTableLogic } from './dataWarehouseTableLogic'

export function DatawarehouseTableForm(): JSX.Element {
    return (
        <Form formKey="table" logic={dataWarehouseTableLogic} className="space-y-4" enableFormOnSubmit>
            <div className="flex flex-col gap-2 max-w-160">
                <Field name="name" label="Table Name">
                    <LemonInput
                        data-attr="table-name"
                        className="ph-ignore-input"
                        autoFocus
                        placeholder="Examples: stripe_invoice, hubspot_contacts, users"
                        autoComplete="off"
                        autoCapitalize="off"
                        autoCorrect="off"
                        spellCheck={false}
                    />
                </Field>
                <div className="text-muted text-xs mb-4">This will be the table name used when writing queries</div>
                <Field name="url_pattern" label="Files URL pattern">
                    <LemonInput
                        data-attr="table-name"
                        className="ph-ignore-input"
                        autoFocus
                        placeholder="eg: https://your-org.s3.amazonaws.com/airbyte/stripe/invoices/*.pqt"
                        autoComplete="off"
                        autoCapitalize="off"
                        autoCorrect="off"
                        spellCheck={false}
                    />
                </Field>
                <div className="text-muted text-xs mb-4">
                    You can use <strong>*</strong> to select multiple files.
                </div>
                <Field name="format" label="File format" className="w-max">
                    <LemonSelect
                        data-attr="table-format"
                        options={[
                            { label: 'Parquet (recommended)', value: 'Parquet' },
                            { label: 'CSV', value: 'CSV' },
                            { label: 'JSON', value: 'JSONEachRow' },
                        ]}
                    />
                </Field>
                <Field name={['credential', 'access_key']} label="Access Key">
                    <LemonInput
                        data-attr="access-key"
                        className="ph-ignore-input"
                        autoFocus
                        placeholder="eg: AKIAIOSFODNN7EXAMPLE"
                        autoComplete="off"
                        autoCapitalize="off"
                        autoCorrect="off"
                        spellCheck={false}
                    />
                </Field>
                <Field name={['credential', 'access_secret']} label="Access Secret">
                    <LemonInput
                        data-attr="access-secret"
                        className="ph-ignore-input"
                        autoFocus
                        type="password"
                        placeholder="eg: wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
                        autoComplete="off"
                        autoCapitalize="off"
                        autoCorrect="off"
                        spellCheck={false}
                    />
                </Field>
            </div>
        </Form>
    )
}
