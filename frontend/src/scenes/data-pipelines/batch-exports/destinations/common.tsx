import React from 'react'

import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

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
