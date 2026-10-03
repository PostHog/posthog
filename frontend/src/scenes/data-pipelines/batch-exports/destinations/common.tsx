import { LemonCheckbox, LemonInput, LemonSelect, LemonSwitch, Link } from '@posthog/lemon-ui'

import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect'

import type { DatabaseSchemaField } from '~/queries/schema/schema-general'
import type { IntegrationKind } from '~/types'

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

// Mirrors COMPRESSION_EXTENSIONS in the backend's destinations/constants.py.
const COMPRESSION_EXTENSIONS: Record<string, string> = {
    gzip: 'gz',
    snappy: 'sz',
    brotli: 'br',
    zstd: 'zst',
    lz4: 'lz4',
}

export function isSelectedCompressionOptionValid(fileFormat: string | undefined, value: string | null): boolean {
    if (fileFormat === 'Parquet') {
        return PARQUET_COMPRESSION_OPTIONS.some((option) => option.value === value)
    } else if (fileFormat === 'JSONLines') {
        return JSONLINES_COMPRESSION_OPTIONS.some((option) => option.value === value)
    }
    return false
}

// Compression select whose options adapt to the currently-selected file format. Used by S3 and
// AzureBlob, which share file_format/compression semantics. The form logic resets compression to a
// valid value when file_format changes (see batchExportConfigFormLogic's setConfigurationValue).
export function CompressionField({ fileFormat }: { fileFormat: string | undefined }): JSX.Element {
    const compressionOptions =
        fileFormat === 'Parquet'
            ? PARQUET_COMPRESSION_OPTIONS
            : fileFormat === 'JSONLines'
              ? JSONLINES_COMPRESSION_OPTIONS
              : []

    return (
        <LemonField name="compression" label="Compression" className="flex-1">
            <LemonSelect
                options={compressionOptions}
                placeholder={!fileFormat ? 'Select file format first' : undefined}
            />
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

interface ParquetExtensionFieldProps {
    isNew: boolean
    fileFormat: string | undefined
    compression: string | null | undefined
    savedConfig?: Record<string, any> | null
}

// The setting only changes a name that carries a codec, so it needs compressed Parquet on both
// sides: the form values say what the export is about to write, `savedConfig` what it has been
// writing. Without a codec the name is `.parquet` either way and the switch would do nothing.
//
// Reading the saved side also stops the field disappearing the moment the user switches it on.
export function shouldShowParquetExtensionField({
    isNew,
    fileFormat,
    compression,
    savedConfig,
}: ParquetExtensionFieldProps): boolean {
    if (isNew || fileFormat !== 'Parquet' || !compression || !COMPRESSION_EXTENSIONS[compression]) {
        return false
    }
    const wroteCompressedParquet = savedConfig?.file_format === 'Parquet' && !!savedConfig.compression
    return wroteCompressedParquet && savedConfig?.legacy_parquet_extension !== false
}

export function ParquetExtensionField(props: ParquetExtensionFieldProps): JSX.Element | null {
    if (!shouldShowParquetExtensionField(props)) {
        return null
    }

    const legacyExtension = `.parquet.${COMPRESSION_EXTENSIONS[props.compression as string]}`

    return (
        <LemonField
            name="legacy_parquet_extension"
            label="File extension"
            help="Note: switching this on cannot be undone; after you save, the setting no longer appears for this export."
            info={
                <>
                    Parquet records the compression codec inside the file, so the standard extension is{' '}
                    <code>.parquet</code> regardless of the codec. This export writes <code>{legacyExtension}</code>{' '}
                    instead. Turn this on to name new files <code>.parquet</code>. Files already exported keep their
                    names.
                </>
            }
        >
            {({ value, onChange }) => (
                <LemonSwitch
                    label={`Use the standard .parquet extension rather than ${legacyExtension}`}
                    // The stored setting names the legacy behaviour, so the switch reads the other
                    // way round: turning it on opts the export out of that behaviour.
                    checked={value === false}
                    onChange={(checked) => onChange(!checked)}
                    fullWidth
                    bordered
                />
            )}
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

// Included in every destination's event table preview except HTTP, which posts capture-format
// payloads and does not export the column.
export const PERSON_PROPERTIES_EVENT_FIELD: Record<string, DatabaseSchemaField> = {
    person_properties: {
        name: 'person_properties',
        hogql_value: "nullIf(person_properties, '')",
        type: 'string',
        schema_valid: true,
    },
}

// Event table preview columns shared by every S3-family destination (S3, AwsS3, S3Compatible).
export const S3_FAMILY_EVENT_TABLE_EXTRA_FIELDS: Record<string, DatabaseSchemaField> = {
    person_id: {
        name: 'person_id',
        hogql_value: 'toString(person_id)',
        type: 'string',
        schema_valid: true,
    },
    ...PERSON_PROPERTIES_EVENT_FIELD,
    created_at: {
        name: 'created_at',
        hogql_value: 'created_at',
        type: 'datetime',
        schema_valid: true,
    },
}

// Shared form fields for the AwsS3 and S3Compatible destinations. Per-destination definitions toggle
// the AWS-only (encryption/KMS) and S3-compatible-only (virtual-style) blocks and supply the region
// option set; everything else is identical.
//
// Credentials, and the endpoint URL for S3-compatible providers, live in the linked Integration, so
// this form only picks the integration.
export function S3FamilyFields({
    isNew,
    formValues,
    savedConfig,
    regionOptions,
    allowCustomRegion = false,
    showEncryption,
    showVirtualStyleAddressing,
    integrationKind,
}: {
    isNew: boolean
    formValues: Record<string, any>
    savedConfig?: Record<string, any> | null
    regionOptions: { value: string; label: string }[]
    // Let users type a region not in the preset list. True for the S3-compatible catch-all, where we
    // can't enumerate every provider's regions; false for AWS S3, whose regions are a closed set.
    allowCustomRegion?: boolean
    showEncryption: boolean
    showVirtualStyleAddressing: boolean
    // This destination authenticates via an Integration of this kind.
    integrationKind: IntegrationKind
}): JSX.Element {
    return (
        <>
            <LemonField name="integration_id" label="Integration">
                {({ value, onChange }) => (
                    <IntegrationChoice integration={integrationKind} value={value} onChange={onChange} />
                )}
            </LemonField>

            <div className="flex gap-4">
                <LemonField name="bucket_name" label="Bucket" className="flex-1">
                    <LemonInput placeholder="e.g. my-bucket" />
                </LemonField>
                <LemonField name="region" label="Region" className="flex-1">
                    {({ value, onChange }) =>
                        allowCustomRegion ? (
                            <LemonInputSelect
                                mode="single"
                                allowCustomValues
                                fullWidth
                                value={value ? [value] : []}
                                onChange={(vals) => onChange((vals[0] ?? '').trim())}
                                options={regionOptions.map((o) => ({ key: o.value, label: o.label }))}
                                placeholder="Select or enter a region"
                            />
                        ) : (
                            <LemonSelect value={value} onChange={onChange} options={regionOptions} />
                        )
                    }
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
                <CompressionField fileFormat={formValues.file_format} />

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

                {/* The KMS key is config, not a credential, and only applies to aws:kms encryption. */}
                {showEncryption && formValues.encryption == 'aws:kms' && (
                    <LemonField name="kms_key_id" label="AWS KMS Key ID" className="flex-1">
                        <LemonInput
                            placeholder={isNew ? 'e.g. 1234abcd-12ab-34cd-56ef-1234567890ab' : 'leave unchanged'}
                        />
                    </LemonField>
                )}
            </div>

            <ParquetExtensionField
                isNew={isNew}
                fileFormat={formValues.file_format}
                compression={formValues.compression}
                savedConfig={savedConfig}
            />

            {showVirtualStyleAddressing && (
                <LemonField
                    name="use_virtual_style_addressing"
                    label="Virtual style addressing"
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
