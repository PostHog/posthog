import { LemonInput } from '@posthog/lemon-ui'

import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { LemonField } from 'lib/lemon-ui/LemonField'

import {
    CompressionField,
    FileFormatField,
    MaxFileSizeField,
    PERSON_EVENT_FIELDS,
    ParquetExtensionField,
    validateAzureContainerName,
} from './common'
import type { DestinationDefinition } from './types'

export const azureBlobDefinition: DestinationDefinition = {
    type: 'AzureBlob',
    usesIntegration: true,
    defaults: () => ({
        file_format: 'Parquet',
        compression: 'zstd',
    }),
    requiredFields: ({ isNew }) => ['integration_id', 'container_name', ...(isNew ? ['file_format'] : [])],
    configKeys: [
        'container_name',
        'prefix',
        'compression',
        'file_format',
        'max_file_size_mb',
        'legacy_parquet_extension',
    ],
    validate: (formValues) => ({
        container_name: validateAzureContainerName(formValues.container_name),
    }),
    eventTableExtraFields: {
        team_id: {
            name: 'team_id',
            hogql_value: 'team_id',
            type: 'integer',
            schema_valid: true,
        },
        ...PERSON_EVENT_FIELDS,
        azure_blob_ingested_timestamp: {
            name: 'azure_blob_ingested_timestamp',
            hogql_value: 'NOW64()',
            type: 'datetime',
            schema_valid: true,
        },
    },
    eventTableOverrides: { includeGenericPersonFields: false },
    Fields: function AzureBlobFields({ isNew, formValues, savedConfig }) {
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

                <ParquetExtensionField
                    isNew={isNew}
                    fileFormat={formValues.file_format}
                    compression={formValues.compression}
                    savedConfig={savedConfig}
                />
            </>
        )
    },
}
