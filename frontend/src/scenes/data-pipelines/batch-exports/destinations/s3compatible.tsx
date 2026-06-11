import { S3FamilyFields, S3_FAMILY_EVENT_TABLE_EXTRA_FIELDS, S3_REGION_OPTIONS, validateBucketName } from './common'
import type { DestinationDefinition } from './types'

// Catch-all for any non-AWS S3-compatible object storage. Requires an endpoint URL and exposes
// virtual-style addressing; no AWS-specific encryption / KMS fields.
export const s3CompatibleDefinition: DestinationDefinition = {
    type: 'S3Compatible',
    defaults: () => ({
        file_format: 'Parquet',
        compression: 'zstd',
    }),
    requiredFields: ({ isNew }) => [
        'bucket_name',
        'region',
        'prefix',
        'endpoint_url',
        ...(isNew ? ['aws_access_key_id'] : []),
        ...(isNew ? ['aws_secret_access_key'] : []),
        ...(isNew ? ['file_format'] : []),
    ],
    validate: (formValues) => ({
        bucket_name: validateBucketName(formValues.bucket_name),
    }),
    eventTableExtraFields: S3_FAMILY_EVENT_TABLE_EXTRA_FIELDS,
    eventTableOverrides: { includeGenericPersonFields: false },
    Fields: function S3CompatibleFields({ isNew, formValues, configurationChanged }) {
        return (
            <S3FamilyFields
                isNew={isNew}
                formValues={formValues}
                configurationChanged={configurationChanged}
                regionOptions={S3_REGION_OPTIONS}
                awsBranded={false}
                allowCustomRegion
                showEncryption={false}
                showEndpointUrl
                endpointUrlRequired
                showVirtualStyleAddressing
            />
        )
    },
}
