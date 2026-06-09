import React, { type ReactNode } from 'react'

import { LemonCheckbox, LemonInput, LemonSelect, Link } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import type { DatabaseSchemaField } from '~/queries/schema/schema-general'

// Bucket naming rules (supports both S3 and GCS):
// S3: https://docs.aws.amazon.com/AmazonS3/latest/userguide/bucketnamingrules.html
// GCS: https://cloud.google.com/storage/docs/buckets#naming
const BUCKET_NAME_REGEX = /^[a-z0-9][a-z0-9._-]*[a-z0-9]$|^[a-z0-9]$/
const IP_ADDRESS_REGEX = /^(\d{1,3}\.){3}\d{1,3}$/

export function validateBucketName(bucketName: string | undefined): string | undefined {
    if (!bucketName) {
        return undefined
    }

    if (/\s/.test(bucketName)) {
        return 'Bucket name cannot contain whitespace'
    }

    if (bucketName !== bucketName.toLowerCase()) {
        return 'Bucket name must be lowercase'
    }

    if (bucketName.includes('..')) {
        return 'Bucket name cannot contain consecutive periods'
    }

    if (IP_ADDRESS_REGEX.test(bucketName)) {
        return 'Bucket name cannot be formatted as an IP address'
    }

    if (!BUCKET_NAME_REGEX.test(bucketName)) {
        return 'Bucket name can only contain lowercase letters, numbers, hyphens, and periods, and must start and end with a letter or number'
    }

    return undefined
}

export function validateAzureContainerName(name: string | undefined): string | undefined {
    if (!name) {
        return undefined
    }
    if (!/^[a-z0-9][a-z0-9-]*[a-z0-9]$/.test(name) && name.length > 1) {
        return 'Must be lowercase letters, numbers, and hyphens; start and end with letter or number'
    }
    if (/--/.test(name)) {
        return 'Cannot contain consecutive hyphens'
    }
    return undefined
}

// Full S3 region list, including GCP Cloud Storage and a handful of S3-compatible providers.
export const S3_REGION_OPTIONS: { value: string; label: string }[] = [
    { value: 'us-east-1', label: 'US East (N. Virginia)' },
    { value: 'us-east-2', label: 'US East (Ohio)' },
    { value: 'us-west-1', label: 'US West (N. California)' },
    { value: 'us-west-2', label: 'US West (Oregon)' },
    { value: 'af-south-1', label: 'Africa (Cape Town)' },
    { value: 'ap-east-1', label: 'Asia Pacific (Hong Kong)' },
    { value: 'ap-south-1', label: 'Asia Pacific (Mumbai)' },
    { value: 'ap-northeast-3', label: 'Asia Pacific (Osaka-Local)' },
    { value: 'ap-northeast-2', label: 'Asia Pacific (Seoul)' },
    { value: 'ap-southeast-1', label: 'Asia Pacific (Singapore)' },
    { value: 'ap-southeast-2', label: 'Asia Pacific (Sydney)' },
    { value: 'ap-northeast-1', label: 'Asia Pacific (Tokyo)' },
    { value: 'ca-central-1', label: 'Canada (Central)' },
    { value: 'cn-north-1', label: 'China (Beijing)' },
    { value: 'cn-northwest-1', label: 'China (Ningxia)' },
    { value: 'eu-central-1', label: 'Europe (Frankfurt)' },
    { value: 'eu-west-1', label: 'Europe (Ireland)' },
    { value: 'eu-west-2', label: 'Europe (London)' },
    { value: 'eu-south-1', label: 'Europe (Milan)' },
    { value: 'eu-west-3', label: 'Europe (Paris)' },
    { value: 'eu-north-1', label: 'Europe (Stockholm)' },
    { value: 'me-east-1', label: 'Middle East (Dubai)' },
    { value: 'me-south-1', label: 'Middle East (Bahrain)' },
    { value: 'me-central-1', label: 'Middle East (Riyadh)' },
    { value: 'sa-east-1', label: 'South America (São Paulo)' },
    { value: 'us-central1', label: 'GCP — US Central (Iowa)' },
    { value: 'europe-west4', label: 'GCP — Europe (Netherlands)' },
    { value: 'auto', label: 'Automatic (AUTO)' },
    { value: 'apac', label: 'Asia Pacific (APAC)' },
    { value: 'eeur', label: 'Eastern Europe (EEUR)' },
    { value: 'enam', label: 'Eastern North America (ENAM)' },
    { value: 'weur', label: 'Western Europe (WEUR)' },
    { value: 'wnam', label: 'Western North America (WNAM)' },
    { value: 'gra', label: 'Gravelines (GRA)' },
    { value: 'rbx', label: 'Roubaix (RBX)' },
    { value: 'sbg', label: 'Strasbourg (SBG)' },
    { value: 'eu-west-par', label: 'Paris (PAR)' },
    { value: 'eu-south-mil', label: 'Milan (MIL)' },
    { value: 'de', label: 'Frankfurt (DE)' },
    { value: 'uk', label: 'London (UK)' },
    { value: 'waw', label: 'Warsaw (WAW)' },
    { value: 'bhs', label: 'Beauharnois (BHS)' },
    { value: 'ca-east-tor', label: 'Toronto (TOR)' },
    { value: 'sgp', label: 'Singapore (SGP)' },
    { value: 'ap-southeast-syd', label: 'Sydney (SYD)' },
    { value: 'ap-south-mum', label: 'Mumbai (MUM)' },
]

// AWS-only region subset used for the Redshift COPY S3 staging bucket.
export const AWS_ONLY_REGION_OPTIONS: { value: string; label: string }[] = [
    { value: 'us-east-1', label: 'US East (N. Virginia)' },
    { value: 'us-east-2', label: 'US East (Ohio)' },
    { value: 'us-west-1', label: 'US West (N. California)' },
    { value: 'us-west-2', label: 'US West (Oregon)' },
    { value: 'af-south-1', label: 'Africa (Cape Town)' },
    { value: 'ap-east-1', label: 'Asia Pacific (Hong Kong)' },
    { value: 'ap-south-1', label: 'Asia Pacific (Mumbai)' },
    { value: 'ap-northeast-3', label: 'Asia Pacific (Osaka-Local)' },
    { value: 'ap-northeast-2', label: 'Asia Pacific (Seoul)' },
    { value: 'ap-southeast-1', label: 'Asia Pacific (Singapore)' },
    { value: 'ap-southeast-2', label: 'Asia Pacific (Sydney)' },
    { value: 'ap-northeast-1', label: 'Asia Pacific (Tokyo)' },
    { value: 'ca-central-1', label: 'Canada (Central)' },
    { value: 'cn-north-1', label: 'China (Beijing)' },
    { value: 'cn-northwest-1', label: 'China (Ningxia)' },
    { value: 'eu-central-1', label: 'Europe (Frankfurt)' },
    { value: 'eu-west-1', label: 'Europe (Ireland)' },
    { value: 'eu-west-2', label: 'Europe (London)' },
    { value: 'eu-south-1', label: 'Europe (Milan)' },
    { value: 'eu-west-3', label: 'Europe (Paris)' },
    { value: 'eu-north-1', label: 'Europe (Stockholm)' },
    { value: 'me-south-1', label: 'Middle East (Bahrain)' },
    { value: 'me-central-1', label: 'Middle East (Riyadh)' },
    { value: 'sa-east-1', label: 'South America (São Paulo)' },
]

export const FILE_FORMAT_OPTIONS: { value: string; label: string }[] = [
    { value: 'Parquet', label: 'Apache Parquet' },
    { value: 'JSONLines', label: 'JSON lines' },
]

const PARQUET_COMPRESSION_OPTIONS = [
    { value: 'zstd', label: 'zstd' },
    { value: 'lz4', label: 'lz4' },
    { value: 'snappy', label: 'snappy' },
    { value: 'gzip', label: 'gzip' },
    { value: 'brotli', label: 'brotli' },
    { value: null, label: 'No compression' },
]

const JSONLINES_COMPRESSION_OPTIONS = [
    { value: 'gzip', label: 'gzip' },
    { value: 'brotli', label: 'brotli' },
    { value: null, label: 'No compression' },
]

// Compression select that adapts its options to the currently-selected file format and self-corrects
// invalid combinations. Used by S3 and AzureBlob, which share file_format/compression semantics.
export function CompressionField({
    fileFormat,
    isNew,
    configurationChanged,
}: {
    fileFormat: string | undefined
    isNew: boolean
    configurationChanged: boolean
}): JSX.Element {
    return (
        <LemonField name="compression" label="Compression" className="flex-1">
            {({ value, onChange }) => {
                const compressionOptions =
                    fileFormat === 'Parquet'
                        ? PARQUET_COMPRESSION_OPTIONS
                        : fileFormat === 'JSONLines'
                          ? JSONLINES_COMPRESSION_OPTIONS
                          : []

                const isSelectedCompressionOptionValid = (val: string | null): boolean => {
                    if (fileFormat === 'Parquet') {
                        return PARQUET_COMPRESSION_OPTIONS.some((option) => option.value === val)
                    } else if (fileFormat === 'JSONLines') {
                        return JSONLINES_COMPRESSION_OPTIONS.some((option) => option.value === val)
                    }
                    return false
                }

                React.useEffect(() => {
                    if (!configurationChanged) {
                        return
                    }
                    if (isNew && fileFormat === 'JSONLines') {
                        onChange(null)
                    } else if (isNew && fileFormat === 'Parquet') {
                        onChange('zstd')
                    } else if (!isSelectedCompressionOptionValid(value)) {
                        onChange(null)
                    }
                }, [configurationChanged, fileFormat, isNew]) // oxlint-disable-line react-hooks/exhaustive-deps

                return (
                    <LemonSelect
                        options={compressionOptions}
                        value={value}
                        onChange={onChange}
                        placeholder={!fileFormat ? 'Select file format first' : undefined}
                    />
                )
            }}
        </LemonField>
    )
}

export function FileFormatField(): JSX.Element {
    return (
        <LemonField
            name="file_format"
            label="Format"
            className="flex-1"
            info="We recommend Parquet with zstd compression for the best performance"
        >
            <LemonSelect options={FILE_FORMAT_OPTIONS} />
        </LemonField>
    )
}

export function MaxFileSizeField(): JSX.Element {
    return (
        <LemonField
            name="max_file_size_mb"
            label="Max file size (MiB)"
            showOptional
            className="flex-1"
            info="Files over this max file size will be split into multiple files. Leave empty or set to 0 for no splitting regardless of file size."
        >
            <LemonInput type="number" min={0} />
        </LemonField>
    )
}

// Event table preview columns shared by every S3-family destination (S3, AwsS3, S3Compatible).
export const S3_FAMILY_EVENT_TABLE_EXTRA_FIELDS: Record<string, DatabaseSchemaField> = {
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
}

// Shared form fields for the S3-family destinations (S3 legacy, AwsS3, S3Compatible). Per-destination
// definitions toggle the AWS-only (encryption/KMS) and S3-compatible-only (endpoint/virtual-style)
// blocks and supply the region option set; everything else is identical.
export function S3FamilyFields({
    isNew,
    formValues,
    configurationChanged,
    regionOptions,
    awsBranded,
    showEncryption,
    showEndpointUrl,
    endpointUrlRequired = false,
    showVirtualStyleAddressing,
    endpointHelpText,
}: {
    isNew: boolean
    formValues: Record<string, any>
    configurationChanged: boolean
    regionOptions: { value: string; label: string }[]
    // Prefix the credential labels with "AWS" — only true for AWS S3, not the S3-compatible catch-all.
    awsBranded: boolean
    showEncryption: boolean
    showEndpointUrl: boolean
    endpointUrlRequired?: boolean
    showVirtualStyleAddressing: boolean
    endpointHelpText?: ReactNode
}): JSX.Element {
    return (
        <>
            <div className="flex gap-4">
                <LemonField name="bucket_name" label="Bucket" className="flex-1">
                    <LemonInput placeholder="e.g. my-bucket" />
                </LemonField>
                <LemonField name="region" label="Region" className="flex-1">
                    <LemonSelect options={regionOptions} />
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

                {showEncryption && (
                    <LemonField name="encryption" label="Encryption" className="flex-1">
                        <LemonSelect
                            options={[
                                { value: 'AES256', label: 'AES256' },
                                { value: 'aws:kms', label: 'aws:kms' },
                                { value: null, label: 'No encryption' },
                            ]}
                        />
                    </LemonField>
                )}
            </div>

            <div className="flex gap-4">
                <LemonField
                    name="aws_access_key_id"
                    label={awsBranded ? 'AWS Access Key ID' : 'Access Key ID'}
                    className="flex-1"
                >
                    <LemonInput
                        placeholder={isNew ? 'e.g. AKIAIOSFODNN7EXAMPLE' : 'Leave unchanged'}
                        autoComplete="off"
                    />
                </LemonField>

                <LemonField
                    name="aws_secret_access_key"
                    label={awsBranded ? 'AWS Secret Access Key' : 'Secret Access Key'}
                    className="flex-1"
                >
                    <LemonInput
                        placeholder={isNew ? 'e.g. secret-key' : 'Leave unchanged'}
                        type="password"
                        autoComplete="new-password"
                    />
                </LemonField>

                {showEncryption && formValues.encryption == 'aws:kms' && (
                    <LemonField name="kms_key_id" label="AWS KMS Key ID" className="flex-1">
                        <LemonInput
                            placeholder={isNew ? 'e.g. 1234abcd-12ab-34cd-56ef-1234567890ab' : 'leave unchanged'}
                        />
                    </LemonField>
                )}
            </div>

            {showEndpointUrl && (
                <LemonField
                    name="endpoint_url"
                    label="Endpoint URL"
                    showOptional={!endpointUrlRequired}
                    info={
                        endpointHelpText ?? (
                            <>Only required if exporting to an S3-compatible blob storage (like MinIO)</>
                        )
                    }
                >
                    <LemonInput placeholder={isNew ? 'e.g. https://your-minio-host:9000' : 'Leave unchanged'} />
                </LemonField>
            )}

            {showVirtualStyleAddressing && (
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
            )}
        </>
    )
}

// Generic person-related event columns shared by Postgres, Redshift, Snowflake, BigQuery, HTTP.
// S3 and Databricks override these (S3 uses person_id/person_properties/created_at; Databricks
// emits a different team_id+ingestion-timestamp pair).
export function genericPersonEventFields(opts: {
    teamIdHogql: string
    setName: string
    setOnceName: string
}): Record<string, DatabaseSchemaField> {
    return {
        team_id: {
            name: 'team_id',
            hogql_value: opts.teamIdHogql,
            type: 'integer',
            schema_valid: true,
        },
        set: {
            name: opts.setName,
            hogql_value: "nullIf(JSONExtractString(properties, '$set'), '')",
            type: 'string',
            schema_valid: true,
        },
        set_once: {
            name: opts.setOnceName,
            hogql_value: "nullIf(JSONExtractString(properties, '$set_once'), '')",
            type: 'string',
            schema_valid: true,
        },
        site_url: {
            name: 'site_url',
            hogql_value: "''",
            type: 'string',
            schema_valid: true,
        },
        ip: {
            name: 'ip',
            hogql_value: "nullIf(JSONExtractString(properties, '$ip'), '')",
            type: 'string',
            schema_valid: true,
        },
        elements_chain: {
            name: 'elements',
            hogql_value: 'toJSONString(elements_chain)',
            type: 'string',
            schema_valid: true,
        },
    }
}
