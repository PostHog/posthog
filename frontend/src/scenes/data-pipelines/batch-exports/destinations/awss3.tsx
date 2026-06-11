import {
    AWS_ONLY_REGION_OPTIONS,
    S3FamilyFields,
    S3_FAMILY_EVENT_TABLE_EXTRA_FIELDS,
    validateBucketName,
} from './common'
import type { DestinationDefinition } from './types'

// AWS S3 — the first-class destination for buckets hosted on AWS. No endpoint or virtual-style
// addressing (those are derived from the AWS region); encryption + KMS are AWS-specific so they stay.
export const awsS3Definition: DestinationDefinition = {
    type: 'AwsS3',
    defaults: () => ({
        file_format: 'Parquet',
        compression: 'zstd',
    }),
    requiredFields: ({ isNew }) => [
        'bucket_name',
        'region',
        'prefix',
        ...(isNew ? ['aws_access_key_id'] : []),
        ...(isNew ? ['aws_secret_access_key'] : []),
        ...(isNew ? ['file_format'] : []),
    ],
    validate: (formValues) => ({
        bucket_name: validateBucketName(formValues.bucket_name),
    }),
    eventTableExtraFields: S3_FAMILY_EVENT_TABLE_EXTRA_FIELDS,
    eventTableOverrides: { includeGenericPersonFields: false },
    Fields: function AwsS3Fields({ isNew, formValues, configurationChanged }) {
        return (
            <S3FamilyFields
                isNew={isNew}
                formValues={formValues}
                configurationChanged={configurationChanged}
                regionOptions={AWS_ONLY_REGION_OPTIONS}
                awsBranded
                showEncryption
                showEndpointUrl={false}
                showVirtualStyleAddressing={false}
            />
        )
    },
}
