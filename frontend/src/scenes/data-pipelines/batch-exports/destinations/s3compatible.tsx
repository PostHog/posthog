import { S3FamilyFields, S3_FAMILY_EVENT_TABLE_EXTRA_FIELDS, S3_REGION_OPTIONS, validateBucketName } from './common'
import type { DestinationDefinition } from './types'

// Catch-all for any non-AWS S3-compatible object storage. Requires an endpoint URL and exposes
// virtual-style addressing; no AWS-specific encryption / KMS fields.
//
// New exports authenticate via an `s3-compatible` Integration (which also carries the endpoint URL);
// exports created before integrations existed keep their inline credentials + endpoint (grandfathered),
// detected by the absence of `integration_id`.
export const s3CompatibleDefinition: DestinationDefinition = {
    type: 'S3Compatible',
    usesIntegration: true,
    defaults: () => ({
        file_format: 'Parquet',
        compression: 'zstd',
    }),
    requiredFields: ({ isNew, formValues }) => {
        if (isNew || formValues.integration_id) {
            // New exports must pick an integration (endpoint_url lives on it); existing
            // integration-backed exports keep theirs.
            return [...(isNew ? ['integration_id', 'file_format'] : []), 'bucket_name', 'region', 'prefix']
        }
        // Grandfathered inline-credential exports keep their original fields, including endpoint_url.
        return ['bucket_name', 'region', 'prefix', 'endpoint_url']
    },
    // The credential keys remain allowlisted for grandfathered inline exports.
    // TODO: clean up once fully migrated to integration-based credentials
    configKeys: [
        'bucket_name',
        'region',
        'prefix',
        'file_format',
        'compression',
        'max_file_size_mb',
        'use_virtual_style_addressing',
        'aws_access_key_id',
        'aws_secret_access_key',
        'endpoint_url',
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
                awsBranded={false}
                allowCustomRegion
                showEncryption={false}
                showEndpointUrl
                endpointUrlRequired
                showVirtualStyleAddressing
                integrationKind="s3-compatible"
                migrationNotice="PostHog is moving S3 batch exports to integration-based credentials. This export will be migrated automatically — no action required."
            />
        )
    },
}
