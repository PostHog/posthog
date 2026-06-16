import { S3FamilyFields, S3_FAMILY_EVENT_TABLE_EXTRA_FIELDS, S3_REGION_OPTIONS, validateBucketName } from './common'
import type { DestinationDefinition } from './types'

// Legacy `S3` destination, kept for batch exports created before the AwsS3 / S3Compatible split and
// hidden from the picker. It shows every S3-family field so any not-yet-reclassified row keeps working.
// TODO: cleanup once all batch exports have been migrated to AwsS3 or S3Compatible
export const s3Definition: DestinationDefinition = {
    type: 'S3',
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
    Fields: function S3Fields({ isNew, formValues, configurationChanged }) {
        return (
            <S3FamilyFields
                isNew={isNew}
                formValues={formValues}
                configurationChanged={configurationChanged}
                regionOptions={S3_REGION_OPTIONS}
                awsBranded
                allowCustomRegion
                showEncryption
                showEndpointUrl
                showVirtualStyleAddressing
            />
        )
    },
}
