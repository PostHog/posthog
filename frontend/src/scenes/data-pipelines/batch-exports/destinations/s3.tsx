import { LemonCheckbox, LemonInput, LemonSelect, Link } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { CompressionField, FileFormatField, MaxFileSizeField, S3_REGION_OPTIONS, validateBucketName } from './common'
import type { DestinationDefinition } from './types'

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
    eventTableExtraFields: {
        person_id: {
            name: 'person_id',
            hogql_value: 'toString(person_id)',
            type: 'string',
            schema_valid: true,
        },
        person_properties: {
            name: 'person_properties',
            hogql_value: "nullIf(person_properties, '')",
            type: 'string',
            schema_valid: true,
        },
        created_at: {
            name: 'created_at',
            hogql_value: 'created_at',
            type: 'datetime',
            schema_valid: true,
        },
    },
    eventTableOverrides: { includeGenericPersonFields: false },
    Fields: function S3Fields({ isNew, formValues, configurationChanged }) {
        return (
            <>
                <div className="flex gap-4">
                    <LemonField name="bucket_name" label="Bucket" className="flex-1">
                        <LemonInput placeholder="e.g. my-bucket" />
                    </LemonField>
                    <LemonField name="region" label="Region" className="flex-1">
                        <LemonSelect options={S3_REGION_OPTIONS} />
                    </LemonField>
                </div>
                <LemonField
                    name="prefix"
                    label="Key prefix"
                    info={
                        <>
                            Template variables are supported. Please check out the{' '}
                            <Link
                                to="https://posthog.com/docs/cdp/batch-exports/s3#s3-key-prefix-template-variables"
                                target="_blank"
                            >
                                docs
                            </Link>{' '}
                            for more information.
                        </>
                    }
                >
                    <LemonInput placeholder="e.g. posthog-events/" />
                </LemonField>

                <div className="flex gap-4">
                    <FileFormatField />
                    <MaxFileSizeField />
                </div>

                <div className="flex gap-4">
                    <CompressionField
                        fileFormat={formValues.file_format}
                        isNew={isNew}
                        configurationChanged={configurationChanged}
                    />

                    <LemonField name="encryption" label="Encryption" className="flex-1">
                        <LemonSelect
                            options={[
                                { value: 'AES256', label: 'AES256' },
                                { value: 'aws:kms', label: 'aws:kms' },
                                { value: null, label: 'No encryption' },
                            ]}
                        />
                    </LemonField>
                </div>

                <div className="flex gap-4">
                    <LemonField name="aws_access_key_id" label="AWS Access Key ID" className="flex-1">
                        <LemonInput
                            placeholder={isNew ? 'e.g. AKIAIOSFODNN7EXAMPLE' : 'Leave unchanged'}
                            autoComplete="off"
                        />
                    </LemonField>

                    <LemonField name="aws_secret_access_key" label="AWS Secret Access Key" className="flex-1">
                        <LemonInput
                            placeholder={isNew ? 'e.g. secret-key' : 'Leave unchanged'}
                            type="password"
                            autoComplete="new-password"
                        />
                    </LemonField>

                    {formValues.encryption == 'aws:kms' && (
                        <LemonField name="kms_key_id" label="AWS KMS Key ID" className="flex-1">
                            <LemonInput
                                placeholder={isNew ? 'e.g. 1234abcd-12ab-34cd-56ef-1234567890ab' : 'leave unchanged'}
                            />
                        </LemonField>
                    )}
                </div>

                <LemonField
                    name="endpoint_url"
                    label="Endpoint URL"
                    showOptional
                    info={<>Only required if exporting to an S3-compatible blob storage (like MinIO)</>}
                >
                    <LemonInput placeholder={isNew ? 'e.g. https://your-minio-host:9000' : 'Leave unchanged'} />
                </LemonField>

                <LemonField
                    name="use_virtual_style_addressing"
                    label="Virtual style addressing"
                    showOptional
                    info={
                        <>
                            Some non-AWS S3-compatible destinations may require this setting enabled. Check your
                            destination's documentation if "virtual hosted style" is required, otherwise leave unchecked
                        </>
                    }
                >
                    <LemonCheckbox
                        bordered
                        label={<span className="flex gap-2 items-center">Use virtual style addressing</span>}
                    />
                </LemonField>
            </>
        )
    },
}
