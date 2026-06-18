import { LemonInput } from '@posthog/lemon-ui'

import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { CompressionField, FileFormatField, MaxFileSizeField, validateAzureContainerName } from './common'
import type { DestinationDefinition } from './types'

export const azureBlobDefinition: DestinationDefinition = {
    type: 'AzureBlob',
    usesIntegration: true,
    defaults: () => ({
        file_format: 'Parquet',
        compression: 'zstd',
    }),
    requiredFields: ({ isNew }) => ['integration_id', 'container_name', ...(isNew ? ['file_format'] : [])],
    configKeys: ['container_name', 'prefix', 'compression', 'file_format', 'max_file_size_mb'],
    validate: (formValues) => ({
        container_name: validateAzureContainerName(formValues.container_name),
    }),
    eventTableOverrides: { teamIdHogql: 'team_id' },
    Fields: function AzureBlobFields({ formValues }) {
        return (
            <>
                <LemonField name="integration_id" label="Azure connection">
                    {({ value, onChange }) => (
                        <IntegrationChoice integration="azure-blob" value={value} onChange={onChange} />
                    )}
                </LemonField>

                <LemonField
                    name="container_name"
                    label="Container name"
                    info={
                        <>
                            The name of the Azure Blob Storage container where data will be exported. The container must
                            already exist.
                        </>
                    }
                >
                    <LemonInput placeholder="my-export-container" />
                </LemonField>

                <LemonField
                    name="prefix"
                    label="Blob prefix"
                    showOptional
                    info={
                        <>
                            Optional prefix for blob names. Supports template variables: {'{year}'}, {'{month}'},{' '}
                            {'{day}'}, {'{hour}'}, {'{minute}'}, {'{data_interval_start}'}, {'{data_interval_end}'}.
                        </>
                    }
                >
                    <LemonInput placeholder="posthog/events/" />
                </LemonField>

                <div className="flex gap-4">
                    <FileFormatField />
                    <MaxFileSizeField />
                </div>

                <CompressionField fileFormat={formValues.file_format} />
            </>
        )
    },
}
