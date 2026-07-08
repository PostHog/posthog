import { type ReactNode } from 'react'

import { LemonBanner, LemonCheckbox, LemonInput, LemonSelect, Link } from '@posthog/lemon-ui'

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

// S3-family region list spanning AWS, Google Cloud Storage, Cloudflare R2, and OVHcloud. Non-AWS
// entries are prefixed with their provider; AWS-style codes are left bare because S3-compatible
// providers (MinIO, Wasabi, etc.) commonly reuse them (e.g. `us-east-1`) as a default region.
export const S3_REGION_OPTIONS: { value: string; label: string }[] = [
    // AWS
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
    // Google Cloud Storage (via the S3-compatible XML API). https://docs.cloud.google.com/storage/docs/locations
    { value: 'northamerica-northeast1', label: 'GCP — Montréal (northamerica-northeast1)' },
    { value: 'northamerica-northeast2', label: 'GCP — Toronto (northamerica-northeast2)' },
    { value: 'northamerica-south1', label: 'GCP — Querétaro (northamerica-south1)' },
    { value: 'us-central1', label: 'GCP — Iowa (us-central1)' },
    { value: 'us-east1', label: 'GCP — South Carolina (us-east1)' },
    { value: 'us-east4', label: 'GCP — Northern Virginia (us-east4)' },
    { value: 'us-east5', label: 'GCP — Columbus (us-east5)' },
    { value: 'us-south1', label: 'GCP — Dallas (us-south1)' },
    { value: 'us-west1', label: 'GCP — Oregon (us-west1)' },
    { value: 'us-west2', label: 'GCP — Los Angeles (us-west2)' },
    { value: 'us-west3', label: 'GCP — Salt Lake City (us-west3)' },
    { value: 'us-west4', label: 'GCP — Las Vegas (us-west4)' },
    { value: 'southamerica-east1', label: 'GCP — São Paulo (southamerica-east1)' },
    { value: 'southamerica-west1', label: 'GCP — Santiago (southamerica-west1)' },
    { value: 'europe-central2', label: 'GCP — Warsaw (europe-central2)' },
    { value: 'europe-north1', label: 'GCP — Finland (europe-north1)' },
    { value: 'europe-north2', label: 'GCP — Stockholm (europe-north2)' },
    { value: 'europe-southwest1', label: 'GCP — Madrid (europe-southwest1)' },
    { value: 'europe-west1', label: 'GCP — Belgium (europe-west1)' },
    { value: 'europe-west2', label: 'GCP — London (europe-west2)' },
    { value: 'europe-west3', label: 'GCP — Frankfurt (europe-west3)' },
    { value: 'europe-west4', label: 'GCP — Netherlands (europe-west4)' },
    { value: 'europe-west6', label: 'GCP — Zürich (europe-west6)' },
    { value: 'europe-west8', label: 'GCP — Milan (europe-west8)' },
    { value: 'europe-west9', label: 'GCP — Paris (europe-west9)' },
    { value: 'europe-west10', label: 'GCP — Berlin (europe-west10)' },
    { value: 'europe-west12', label: 'GCP — Turin (europe-west12)' },
    { value: 'asia-east1', label: 'GCP — Taiwan (asia-east1)' },
    { value: 'asia-east2', label: 'GCP — Hong Kong (asia-east2)' },
    { value: 'asia-northeast1', label: 'GCP — Tokyo (asia-northeast1)' },
    { value: 'asia-northeast2', label: 'GCP — Osaka (asia-northeast2)' },
    { value: 'asia-northeast3', label: 'GCP — Seoul (asia-northeast3)' },
    { value: 'asia-south1', label: 'GCP — Mumbai (asia-south1)' },
    { value: 'asia-south2', label: 'GCP — Delhi (asia-south2)' },
    { value: 'asia-southeast1', label: 'GCP — Singapore (asia-southeast1)' },
    { value: 'asia-southeast2', label: 'GCP — Jakarta (asia-southeast2)' },
    { value: 'asia-southeast3', label: 'GCP — Bangkok (asia-southeast3)' },
    { value: 'me-central1', label: 'GCP — Doha (me-central1)' },
    { value: 'me-central2', label: 'GCP — Dammam (me-central2)' },
    { value: 'me-west1', label: 'GCP — Tel Aviv (me-west1)' },
    { value: 'australia-southeast1', label: 'GCP — Sydney (australia-southeast1)' },
    { value: 'australia-southeast2', label: 'GCP — Melbourne (australia-southeast2)' },
    { value: 'africa-south1', label: 'GCP — Johannesburg (africa-south1)' },
    { value: 'US', label: 'GCP — US (multi-region)' },
    { value: 'EU', label: 'GCP — EU (multi-region)' },
    { value: 'ASIA', label: 'GCP — Asia (multi-region)' },
    // Cloudflare R2 (location hints)
    { value: 'auto', label: 'Cloudflare R2 — Automatic (AUTO)' },
    { value: 'apac', label: 'Cloudflare R2 — Asia Pacific (APAC)' },
    { value: 'eeur', label: 'Cloudflare R2 — Eastern Europe (EEUR)' },
    { value: 'enam', label: 'Cloudflare R2 — Eastern North America (ENAM)' },
    { value: 'oc', label: 'Cloudflare R2 — Oceania (OC)' },
    { value: 'weur', label: 'Cloudflare R2 — Western Europe (WEUR)' },
    { value: 'wnam', label: 'Cloudflare R2 — Western North America (WNAM)' },
    // OVHcloud
    { value: 'gra', label: 'OVH — Gravelines (GRA)' },
    { value: 'rbx', label: 'OVH — Roubaix (RBX)' },
    { value: 'sbg', label: 'OVH — Strasbourg (SBG)' },
    { value: 'eu-west-par', label: 'OVH — Paris (PAR)' },
    { value: 'eu-south-mil', label: 'OVH — Milan (MIL)' },
    { value: 'de', label: 'OVH — Frankfurt (DE)' },
    { value: 'uk', label: 'OVH — London (UK)' },
    { value: 'waw', label: 'OVH — Warsaw (WAW)' },
    { value: 'bhs', label: 'OVH — Beauharnois (BHS)' },
    { value: 'ca-east-tor', label: 'OVH — Toronto (TOR)' },
    { value: 'sgp', label: 'OVH — Singapore (SGP)' },
    { value: 'ap-southeast-syd', label: 'OVH — Sydney (SYD)' },
    { value: 'ap-south-mum', label: 'OVH — Mumbai (MUM)' },
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
//
// New AwsS3/S3Compatible exports authenticate via a linked Integration (pass `integrationKind`);
// grandfathered exports created before integrations existed keep their inline credential UI, detected
// by the absence of a linked integration. Mirrors the Postgres destination's `useIntegration` pattern.
export function S3FamilyFields({
    isNew,
    formValues,
    regionOptions,
    awsBranded,
    allowCustomRegion = false,
    showEncryption,
    showEndpointUrl,
    endpointUrlRequired = false,
    showVirtualStyleAddressing,
    endpointHelpText,
    integrationKind,
    migrationNotice,
}: {
    isNew: boolean
    formValues: Record<string, any>
    regionOptions: { value: string; label: string }[]
    // Prefix the credential labels with "AWS" — only true for AWS S3, not the S3-compatible catch-all.
    awsBranded: boolean
    // Let users type a region not in the preset list. True for the S3-compatible catch-all, where we
    // can't enumerate every provider's regions; false for AWS S3, whose regions are a closed set.
    allowCustomRegion?: boolean
    showEncryption: boolean
    showEndpointUrl: boolean
    endpointUrlRequired?: boolean
    showVirtualStyleAddressing: boolean
    endpointHelpText?: ReactNode
    // When set, this destination authenticates via an Integration of this kind. The credential and
    // endpoint inputs are replaced by an integration picker for new and integration-backed exports.
    integrationKind?: IntegrationKind
    // Banner shown above the fields whenever the inline (non-integration) UI is rendered — used to
    // tell users the export will be migrated to integrations automatically.
    migrationNotice?: ReactNode
}): JSX.Element {
    // New exports must pick an integration; existing ones keep whatever they were created with.
    const useIntegration = !!integrationKind && (isNew || !!formValues.integration_id)

    // The KMS key is a config field (not a credential) that only applies to aws:kms encryption. With
    // inline credentials it sits in the credentials row; in the integration form that row is gone, so
    // it's surfaced next to the encryption select instead. Rendered in exactly one place either way.
    const kmsKeyIdField = showEncryption && formValues.encryption == 'aws:kms' && (
        <LemonField name="kms_key_id" label="AWS KMS Key ID" className="flex-1">
            <LemonInput placeholder={isNew ? 'e.g. 1234abcd-12ab-34cd-56ef-1234567890ab' : 'leave unchanged'} />
        </LemonField>
    )

    return (
        <>
            {!useIntegration && migrationNotice ? <LemonBanner type="warning">{migrationNotice}</LemonBanner> : null}

            {useIntegration && integrationKind ? (
                <LemonField name="integration_id" label="Integration">
                    {({ value, onChange }) => (
                        <IntegrationChoice integration={integrationKind} value={value} onChange={onChange} />
                    )}
                </LemonField>
            ) : null}

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

                {/* With an integration the credentials row is hidden, so the KMS key lives here instead. */}
                {useIntegration && kmsKeyIdField}
            </div>

            {!useIntegration && (
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

                    {kmsKeyIdField}
                </div>
            )}

            {!useIntegration && showEndpointUrl && (
                <LemonField
                    name="endpoint_url"
                    label="Endpoint URL"
                    showOptional={!endpointUrlRequired}
                    info={
                        endpointHelpText ?? (
                            <>
                                The endpoint URL corresponding to your provider (e.g. Cloudflare R2, DigitalOcean
                                Spaces, Supabase, etc.). Works with any S3-compatible storage.
                            </>
                        )
                    }
                >
                    <LemonInput
                        placeholder={isNew ? 'e.g. https://<account-id>.r2.cloudflarestorage.com' : 'Leave unchanged'}
                    />
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
