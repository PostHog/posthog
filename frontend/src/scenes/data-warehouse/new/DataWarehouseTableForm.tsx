import { LemonInput, LemonSelect, Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { Form } from 'kea-forms'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { ManualLinkSourceType } from '~/types'

import { dataWarehouseTableLogic } from './dataWarehouseTableLogic'
import { sourceWizardLogic } from './sourceWizardLogic'

const ProviderMappings: Record<
    ManualLinkSourceType,
    {
        fileUrlPatternPlaceholder: string
        accessKeyPlaceholder: string
        accessKeyLabel: string
        accessSecretLabel: string
    }
> = {
    aws: {
        fileUrlPatternPlaceholder: 'eg: https://your-org.s3.amazonaws.com/airbyte/stripe/invoices/*.pqt',
        accessKeyPlaceholder: 'eg: AKIAIOSFODNN7EXAMPLE',
        accessKeyLabel: 'Access key',
        accessSecretLabel: 'Access secret',
    },
    'google-cloud': {
        fileUrlPatternPlaceholder: 'eg: https://storage.googleapis.com/your-org/airbyte/stripe/invoices/*.pqt',
        accessKeyPlaceholder: 'eg: GOOGTS7C7FUP3AIRVEXAMPLE',
        accessKeyLabel: 'Access ID',
        accessSecretLabel: 'Secret',
    },
    'cloudflare-r2': {
        fileUrlPatternPlaceholder: 'eg: https://your-account-id.r2.cloudflarestorage.com/airbyte/stripe/invoices/*.pqt',
        accessKeyPlaceholder: 'eg: AKIAIOSFODNN7EXAMPLE',
        accessKeyLabel: 'Access key',
        accessSecretLabel: 'Access secret',
    },
    azure: {
        fileUrlPatternPlaceholder:
            'https://your-storage-container.blob.core.windows.net/airbyte/stripe/invoices/*.parquet',
        accessKeyPlaceholder: 'your-storage-container',
        accessKeyLabel: 'Storage account name',
        accessSecretLabel: 'Account key',
    },
}

export function DatawarehouseTableForm(): JSX.Element {
    const { manualLinkingProvider } = useValues(sourceWizardLogic)

    const provider = manualLinkingProvider ?? 'aws'

    return (
        <Form
            formKey="table"
            logic={dataWarehouseTableLogic}
            className="space-y-4"
            enableFormOnSubmit
            autoComplete="off"
        >
            <div className="flex flex-col gap-2 max-w-160">
                <LemonField name="name" label="Table name">
                    <LemonInput
                        data-attr="table-name"
                        className="ph-ignore-input"
                        placeholder="Examples: stripe_invoice, hubspot_contacts, users"
                        autoComplete="off"
                        autoCapitalize="off"
                        autoCorrect="off"
                        spellCheck={false}
                    />
                </LemonField>
                <div className="text-muted text-xs mb-4">This will be the table name used when writing queries</div>
                <LemonField name="url_pattern" label="Files URL pattern">
                    <LemonInput
                        data-attr="table-name"
                        className="ph-ignore-input"
                        placeholder={ProviderMappings[provider].fileUrlPatternPlaceholder}
                        autoComplete="off"
                        autoCapitalize="off"
                        autoCorrect="off"
                        spellCheck={false}
                    />
                </LemonField>
                <div className="text-muted text-xs mb-4">
                    You can use <strong>*</strong> to select multiple files.
                </div>
                <LemonField name="format" label="File format" className="w-max mb-4">
                    <LemonSelect
                        data-attr="table-format"
                        options={[
                            { label: 'Parquet (recommended)', value: 'Parquet' },
                            { label: 'CSV', value: 'CSV' },
                            { label: 'CSV with headers', value: 'CSVWithNames' },
                            { label: 'JSON', value: 'JSONEachRow' },
                            { label: 'Delta', value: 'Delta' },
                        ]}
                    />
                </LemonField>
                <LemonField name={['credential', 'access_key']} label={ProviderMappings[provider].accessKeyLabel}>
                    <LemonInput
                        data-attr="access-key"
                        className="ph-ignore-input"
                        placeholder={ProviderMappings[provider].accessKeyPlaceholder}
                        autoComplete="off"
                        autoCapitalize="off"
                        autoCorrect="off"
                        spellCheck={false}
                    />
                </LemonField>
                <LemonField name={['credential', 'access_secret']} label={ProviderMappings[provider].accessSecretLabel}>
                    <LemonInput
                        data-attr="access-secret"
                        className="ph-ignore-input"
                        type="password"
                        placeholder="eg: wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
                        autoComplete="off"
                        autoCapitalize="off"
                        autoCorrect="off"
                        spellCheck={false}
                    />
                </LemonField>
                {provider === 'google-cloud' && (
                    <div className="text-muted text-xs">
                        We use HMAC keys to access your Google Cloud Storage. Find more about generating them{' '}
                        <Link to="https://cloud.google.com/storage/docs/authentication/hmackeys" target="_new">
                            here
                        </Link>
                    </div>
                )}
            </div>
        </Form>
    )
}
