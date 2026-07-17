import {
    AWS_ONLY_REGION_OPTIONS,
    S3FamilyFields,
    S3_FAMILY_EVENT_TABLE_EXTRA_FIELDS,
    validateBucketName,
} from './common'
import type { DestinationDefinition } from './types'

// AWS S3 — the first-class destination for buckets hosted on AWS. No endpoint or virtual-style
// addressing (those are derived from the AWS region); encryption + KMS are AWS-specific so they stay.
//
// New exports authenticate via an `aws-s3` Integration; exports created before integrations existed
// keep their inline credentials (grandfathered), detected by the absence of `integration_id`.
export const awsS3Definition: DestinationDefinition = {
    type: 'AwsS3',
    usesIntegration: true,
    defaults: () => ({
        file_format: 'Parquet',
        compression: 'zstd',
    }),
    requiredFields: ({ isNew, formValues }) => {
        if (isNew || formValues.integration_id) {
            // New exports must pick an integration; existing integration-backed exports keep theirs.
            return [...(isNew ? ['integration_id', 'file_format'] : []), 'bucket_name', 'region', 'prefix']
        }
        // Grandfathered inline-credential exports keep their original fields when edited.
        return ['bucket_name', 'region', 'prefix']
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
        'encryption',
        'kms_key_id',
        'aws_access_key_id',
        'aws_secret_access_key',
    ],
    validate: (formValues) => ({
        bucket_name: validateBucketName(formValues.bucket_name),
    }),
    eventTableExtraFields: S3_FAMILY_EVENT_TABLE_EXTRA_FIELDS,
    eventTableOverrides: { includeGenericPersonFields: false },
    Fields: function AwsS3Fields({ isNew, formValues }) {
        return (
            <S3FamilyFields
                isNew={isNew}
                formValues={formValues}
                regionOptions={AWS_ONLY_REGION_OPTIONS}
                awsBranded
                showEncryption
                showEndpointUrl={false}
                showVirtualStyleAddressing={false}
                integrationKind="aws-s3"
                migrationNotice="S3 batch exports are moving to integration-based credentials. This export will be migrated automatically — no action required."
            />
        )
    },
}
