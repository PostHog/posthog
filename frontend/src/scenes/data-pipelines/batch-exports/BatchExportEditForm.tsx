import { IconInfo } from '@posthog/icons'
import {
    LemonCalendarSelectInput,
    LemonCheckbox,
    LemonFileInput,
    LemonInput,
    LemonSelect,
    LemonTextArea,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'
import { LemonField } from 'lib/lemon-ui/LemonField'
import React from 'react'

import { BatchExportConfigurationForm } from './types'

export function BatchExportGeneralEditFields({
    isNew,
    isPipeline = false,
    batchExportConfigForm,
}: {
    isNew: boolean
    isPipeline?: boolean
    batchExportConfigForm: BatchExportConfigurationForm
}): JSX.Element {
    return (
        <>
            <div className="deprecated-space-y-4">
                {!isPipeline && (
                    <LemonField name="name" label="Name">
                        <LemonInput placeholder="Name your workflow for future reference" />
                    </LemonField>
                )}
                <div className="flex flex-wrap gap-2 items-start">
                    {(!isPipeline || batchExportConfigForm.end_at) && ( // Not present in the new UI unless grandfathered in
                        <LemonField
                            name="end_at"
                            label="End date"
                            className="flex-1"
                            info={
                                <>
                                    The date up to which data is to be exported. Leaving it unset implies that data
                                    exports will continue forever until this export is paused or deleted.
                                </>
                            }
                        >
                            {({ value, onChange }) => (
                                <LemonCalendarSelectInput
                                    value={value}
                                    onChange={onChange}
                                    placeholder="Select end date (optional)"
                                    clearable
                                />
                            )}
                        </LemonField>
                    )}
                </div>

                {isNew && !isPipeline ? (
                    <LemonField name="paused">
                        <LemonCheckbox
                            bordered
                            label={
                                <span className="flex gap-2 items-center">
                                    Create in paused state
                                    <Tooltip
                                        title={
                                            "If selected, the Batch Exporter will be created but will be 'paused' allowing you to resumed it at a later date."
                                        }
                                    >
                                        <IconInfo className="text-lg text-secondary" />
                                    </Tooltip>
                                </span>
                            }
                        />
                    </LemonField>
                ) : null}
            </div>
        </>
    )
}

export function BatchExportsEditFields({
    isNew,
    batchExportConfigForm,
}: {
    isNew: boolean
    batchExportConfigForm: BatchExportConfigurationForm
}): JSX.Element {
    return (
        <>
            <div className="mt-4 deprecated-space-y-4 max-w-200">
                {batchExportConfigForm.destination === 'S3' ? (
                    <>
                        <div className="flex gap-4">
                            <LemonField name="bucket_name" label="Bucket" className="flex-1">
                                <LemonInput placeholder="e.g. my-bucket" />
                            </LemonField>
                            <LemonField name="region" label="Region" className="flex-1">
                                <LemonSelect
                                    options={[
                                        { value: 'us-east-1', label: 'US East (N. Virginia)' },
                                        { value: 'us-east-2', label: 'US East (Ohio)' },
                                        { value: 'us-west-1', label: 'US West (N. California)' },
                                        { value: 'us-west-2', label: 'US West (Oregon)' },
                                        { value: 'af-south-1', label: 'Africa (Cape Town)' },
                                        { value: 'ap-east-1', label: 'Asia Pacific (Hong Kong)' },
                                        { value: 'ap-south-1', label: 'Asia Pacific (Mumbai)' },
                                        {
                                            value: 'ap-northeast-3',
                                            label: 'Asia Pacific (Osaka-Local)',
                                        },
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
                                        { value: 'auto', label: 'Automatic (AUTO)' },
                                        { value: 'apac', label: 'Asia Pacific (APAC)' },
                                        { value: 'eeur', label: 'Eastern Europe (EEUR)' },
                                        { value: 'enam', label: 'Eastern North America (ENAM)' },
                                        { value: 'weur', label: 'Western Europe (WEUR)' },
                                        { value: 'wnam', label: 'Western North America (WNAM)' },
                                    ]}
                                />
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
                            <LemonField
                                name="file_format"
                                label="Format"
                                className="flex-1"
                                info="We recommend Parquet with zstd compression for the best performance"
                            >
                                <LemonSelect
                                    options={[
                                        { value: 'Parquet', label: 'Apache Parquet' },
                                        { value: 'JSONLines', label: 'JSON lines' },
                                    ]}
                                />
                            </LemonField>

                            <LemonField
                                name="max_file_size_mb"
                                label="Max file size (MiB)"
                                showOptional
                                className="flex-1"
                                info={
                                    <>
                                        Files over this max file size will be split into multiple files. Leave empty or
                                        set to 0 for no splitting regardless of file size
                                    </>
                                }
                            >
                                <LemonInput type="number" min={0} />
                            </LemonField>
                        </div>

                        <div className="flex gap-4">
                            <LemonField name="compression" label="Compression" className="flex-1">
                                {({ value, onChange }) => {
                                    const parquetCompressionOptions = [
                                        { value: 'zstd', label: 'zstd' },
                                        { value: 'lz4', label: 'lz4' },
                                        { value: 'snappy', label: 'snappy' },
                                        { value: 'gzip', label: 'gzip' },
                                        { value: 'brotli', label: 'brotli' },
                                        { value: null, label: 'No compression' },
                                    ]
                                    const jsonLinesCompressionOptions = [
                                        { value: 'gzip', label: 'gzip' },
                                        { value: 'brotli', label: 'brotli' },
                                        { value: null, label: 'No compression' },
                                    ]
                                    const compressionOptions =
                                        batchExportConfigForm.file_format === 'Parquet'
                                            ? parquetCompressionOptions
                                            : batchExportConfigForm.file_format === 'JSONLines'
                                            ? jsonLinesCompressionOptions
                                            : []

                                    const isSelectedCompressionOptionValid = (value: string | null): boolean => {
                                        if (batchExportConfigForm.file_format === 'Parquet') {
                                            return parquetCompressionOptions.some((option) => option.value === value)
                                        } else if (batchExportConfigForm.file_format === 'JSONLines') {
                                            return jsonLinesCompressionOptions.some((option) => option.value === value)
                                        }
                                        return false
                                    }

                                    // Set defaults when file format changes for new destinations
                                    React.useEffect(() => {
                                        if (isNew && batchExportConfigForm.file_format === 'JSONLines') {
                                            onChange(null)
                                        } else if (isNew && batchExportConfigForm.file_format === 'Parquet') {
                                            onChange('zstd')
                                        } else if (!isSelectedCompressionOptionValid(value)) {
                                            // if file format is changed but existing compression is not valid, set to null
                                            onChange(null)
                                        }
                                    }, [batchExportConfigForm.file_format, isNew])

                                    return (
                                        <LemonSelect
                                            options={compressionOptions}
                                            value={value}
                                            onChange={onChange}
                                            placeholder={
                                                !batchExportConfigForm.file_format
                                                    ? 'Select file format first'
                                                    : undefined
                                            }
                                        />
                                    )
                                }}
                            </LemonField>

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
                                <LemonInput placeholder={isNew ? 'e.g. AKIAIOSFODNN7EXAMPLE' : 'Leave unchanged'} />
                            </LemonField>

                            <LemonField name="aws_secret_access_key" label="AWS Secret Access Key" className="flex-1">
                                <LemonInput
                                    placeholder={isNew ? 'e.g. secret-key' : 'Leave unchanged'}
                                    type="password"
                                />
                            </LemonField>

                            {batchExportConfigForm.encryption == 'aws:kms' && (
                                <LemonField name="kms_key_id" label="AWS KMS Key ID" className="flex-1">
                                    <LemonInput
                                        placeholder={
                                            isNew ? 'e.g. 1234abcd-12ab-34cd-56ef-1234567890ab' : 'leave unchanged'
                                        }
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
                                    destination's documentation if "virtual hosted style" is required, otherwise leave
                                    unchecked
                                </>
                            }
                        >
                            <LemonCheckbox
                                bordered
                                label={<span className="flex gap-2 items-center">Use virtual style addressing</span>}
                            />
                        </LemonField>
                    </>
                ) : batchExportConfigForm.destination === 'Snowflake' ? (
                    <>
                        <LemonField name="account" label="Account">
                            <LemonInput placeholder="my-account" />
                        </LemonField>

                        <LemonField name="user" label="User">
                            <LemonInput placeholder={isNew ? 'my-user' : 'Leave unchanged'} />
                        </LemonField>

                        <LemonField name="authentication_type" label="Authentication type" className="flex-1">
                            <LemonSelect
                                options={[
                                    { value: 'password', label: 'Password' },
                                    { value: 'keypair', label: 'Key pair' },
                                ]}
                            />
                        </LemonField>

                        {batchExportConfigForm.authentication_type != 'keypair' && (
                            <LemonField name="password" label="Password">
                                <LemonInput placeholder={isNew ? 'my-password' : 'Leave unchanged'} type="password" />
                            </LemonField>
                        )}

                        {batchExportConfigForm.authentication_type == 'keypair' && (
                            <>
                                <LemonField name="private_key" label="Private key">
                                    <LemonTextArea
                                        className="ph-ignore-input"
                                        placeholder={isNew ? 'my-private-key' : 'Leave unchanged'}
                                        minRows={4}
                                    />
                                </LemonField>

                                <LemonField name="private_key_passphrase" label="Private key passphrase">
                                    <LemonInput placeholder={isNew ? 'my-passphrase' : 'Leave unchanged'} />
                                </LemonField>
                            </>
                        )}

                        <LemonField name="database" label="Database">
                            <LemonInput placeholder="my-database" />
                        </LemonField>

                        <LemonField name="warehouse" label="Warehouse">
                            <LemonInput placeholder="my-warehouse" />
                        </LemonField>

                        <LemonField name="schema" label="Schema">
                            <LemonInput placeholder="my-schema" />
                        </LemonField>

                        <LemonField name="table_name" label="Table name">
                            <LemonInput placeholder="events" />
                        </LemonField>

                        <LemonField name="role" label="Role" showOptional>
                            <LemonInput placeholder="my-role" />
                        </LemonField>
                    </>
                ) : batchExportConfigForm.destination === 'Postgres' ? (
                    <>
                        <LemonField name="user" label="User">
                            <LemonInput placeholder={isNew ? 'my-user' : 'Leave unchanged'} />
                        </LemonField>

                        <LemonField name="password" label="Password">
                            <LemonInput placeholder={isNew ? 'my-password' : 'Leave unchanged'} type="password" />
                        </LemonField>

                        <LemonField name="host" label="Host">
                            <LemonInput placeholder="my-host" />
                        </LemonField>

                        <LemonField name="port" label="Port">
                            <LemonInput placeholder="5432" type="number" min="0" max="65535" />
                        </LemonField>

                        <LemonField name="database" label="Database">
                            <LemonInput placeholder="my-database" />
                        </LemonField>

                        <LemonField name="schema" label="Schema">
                            <LemonInput placeholder="public" />
                        </LemonField>

                        <LemonField name="table_name" label="Table name">
                            <LemonInput placeholder="events" />
                        </LemonField>

                        <LemonField name="has_self_signed_cert">
                            {({ value, onChange }) => (
                                <LemonCheckbox
                                    bordered
                                    label={
                                        <span className="flex gap-2 items-center">
                                            Does your Postgres instance have a self-signed SSL certificate?
                                            <Tooltip title="In most cases, Heroku and RDS users should check this.">
                                                <IconInfo className="text-lg text-secondary" />
                                            </Tooltip>
                                        </span>
                                    }
                                    checked={!!value}
                                    onChange={onChange}
                                />
                            )}
                        </LemonField>
                    </>
                ) : batchExportConfigForm.destination === 'Redshift' ? (
                    <>
                        <LemonField name="user" label="User">
                            <LemonInput placeholder={isNew ? 'my-user' : 'Leave unchanged'} />
                        </LemonField>

                        <LemonField name="password" label="Password">
                            <LemonInput placeholder={isNew ? 'my-password' : 'Leave unchanged'} type="password" />
                        </LemonField>

                        <LemonField name="host" label="Host">
                            <LemonInput placeholder="my-host" />
                        </LemonField>

                        <LemonField name="port" label="Port">
                            <LemonInput placeholder="5439" type="number" min="0" max="65535" />
                        </LemonField>

                        <LemonField name="database" label="Database">
                            <LemonInput placeholder="my-database" />
                        </LemonField>

                        <LemonField name="schema" label="Schema">
                            <LemonInput placeholder="public" />
                        </LemonField>

                        <LemonField name="table_name" label="Table name">
                            <LemonInput placeholder="events" />
                        </LemonField>

                        <LemonField name="properties_data_type" label="Properties data type">
                            <LemonSelect
                                options={[
                                    { value: 'varchar', label: 'VARCHAR(65535)' },
                                    { value: 'super', label: 'SUPER' },
                                ]}
                            />
                        </LemonField>
                    </>
                ) : batchExportConfigForm.destination === 'BigQuery' ? (
                    <>
                        <LemonField name="json_config_file" label="Google Cloud JSON key file">
                            <LemonFileInput accept=".json" multiple={false} />
                        </LemonField>

                        <LemonField name="table_id" label="Table ID">
                            <LemonInput placeholder="events" />
                        </LemonField>

                        <LemonField name="dataset_id" label="Dataset ID">
                            <LemonInput placeholder="dataset" />
                        </LemonField>

                        {isNew ? (
                            <LemonField name="use_json_type" label="Structured fields data type">
                                <LemonCheckbox
                                    bordered
                                    label={
                                        <span className="flex gap-2 items-center">
                                            Export 'properties', 'set', and 'set_once' fields as BigQuery JSON type
                                            <Tooltip title="If left unchecked, these fields will be sent as STRING type. This setting cannot be changed after batch export is created.">
                                                <IconInfo className="text-lg text-secondary" />
                                            </Tooltip>
                                        </span>
                                    }
                                />
                            </LemonField>
                        ) : null}
                    </>
                ) : batchExportConfigForm.destination === 'HTTP' ? (
                    <>
                        <LemonField name="url" label="PostHog region">
                            <LemonSelect
                                options={[
                                    { value: 'https://us.i.posthog.com/batch/', label: 'US' },
                                    { value: 'https://eu.i.posthog.com/batch/', label: 'EU' },
                                ]}
                            />
                        </LemonField>
                        <LemonField name="token" label="Destination project API Key">
                            <LemonInput placeholder="e.g. phc_12345..." />
                        </LemonField>
                    </>
                ) : null}
            </div>
        </>
    )
}
