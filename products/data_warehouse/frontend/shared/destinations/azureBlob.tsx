import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { DEFAULT_PARQUET_COMPRESSION, PARQUET_COMPRESSION_OPTIONS } from './parquetCompression'
import type { WarehouseDestinationDefinition } from './types'

export const azureBlobDefinition: WarehouseDestinationDefinition = {
    type: 'AzureBlob',
    integrationKinds: ['azure-blob'],
    defaults: () => ({ compression: DEFAULT_PARQUET_COMPRESSION }),
    requiredFields: () => ['container_name'],
    configKeys: ['container_name', 'prefix', 'compression'],
    retargetingKeys: ['container_name', 'prefix'],
    Fields: function AzureBlobFields({ isNew }) {
        return (
            <>
                <LemonField name="container_name" label="Container" info="The container must already exist.">
                    <LemonInput
                        placeholder="my-container"
                        disabled={!isNew}
                        data-attr="warehouse-destination-container"
                    />
                </LemonField>
                <LemonField
                    name="prefix"
                    label="Prefix"
                    showOptional
                    info="Folder to write under. Each table gets its own folder below this."
                >
                    <LemonInput placeholder="posthog/" disabled={!isNew} data-attr="warehouse-destination-prefix" />
                </LemonField>
                <LemonField name="compression" label="Compression">
                    <LemonSelect options={PARQUET_COMPRESSION_OPTIONS} data-attr="warehouse-destination-compression" />
                </LemonField>
            </>
        )
    },
}
