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
// Credentials come from a linked `aws-s3` Integration, never from this destination's config.
export const awsS3Definition: DestinationDefinition = {
    type: 'AwsS3',
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
        'encryption',
        'kms_key_id',
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
                showEncryption
                showVirtualStyleAddressing={false}
                integrationKind="aws-s3"
            />
        )
    },
}
