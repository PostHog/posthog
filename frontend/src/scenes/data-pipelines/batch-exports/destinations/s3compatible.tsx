import { S3FamilyFields, S3_FAMILY_EVENT_TABLE_EXTRA_FIELDS, S3_REGION_OPTIONS, validateBucketName } from './common'
import type { DestinationDefinition } from './types'

// Catch-all for any non-AWS S3-compatible object storage. Exposes virtual-style addressing; no
// AWS-specific encryption / KMS fields.
//
// Credentials and the provider endpoint URL come from a linked `s3-compatible` Integration, never
// from this destination's config.
export const s3CompatibleDefinition: DestinationDefinition = {
    type: 'S3Compatible',
    usesIntegration: true,
    defaults: () => ({
        file_format: 'Parquet',
        compression: 'zstd',
    }),
    requiredFields: ({ isNew }) => [
        'integration_id',
        ...(isNew ? ['file_format'] : []),
        'bucket_name',
        'region',
        'prefix',
    ],
    configKeys: [
        'bucket_name',
        'region',
        'prefix',
        'file_format',
        'compression',
        'max_file_size_mb',
        'use_virtual_style_addressing',
    ],
    validate: (formValues) => ({
        bucket_name: validateBucketName(formValues.bucket_name),
    }),
    eventTableExtraFields: S3_FAMILY_EVENT_TABLE_EXTRA_FIELDS,
    eventTableOverrides: { includeGenericPersonFields: false },
    Fields: function S3CompatibleFields({ isNew, formValues }) {
        return (
            <S3FamilyFields
                isNew={isNew}
                formValues={formValues}
                regionOptions={S3_REGION_OPTIONS}
                allowCustomRegion
                showEncryption={false}
                showVirtualStyleAddressing
                integrationKind="s3-compatible"
            />
        )
    },
}
