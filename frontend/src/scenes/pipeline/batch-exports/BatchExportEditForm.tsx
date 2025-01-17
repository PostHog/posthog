import { IconInfo } from '@posthog/icons'
import {
    LemonBanner,
    LemonCalendarSelectInput,
    LemonCheckbox,
    LemonFileInput,
    LemonInput,
    LemonInputSelect,
    LemonSelect,
    LemonButton,
    Tooltip,
} from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { DatabaseTable } from 'scenes/data-management/database/DatabaseTable'
import { QueryPane } from 'scenes/data-warehouse/editor/QueryPane'
import { BatchExportConfigurationForm } from './types'
import { CodeEditor, CodeEditorProps } from 'lib/monaco/CodeEditor'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { HogQLQueryEditor } from '~/queries/nodes/HogQLQuery/HogQLQueryEditor'
import { HogQLQuery } from '~/queries/schema'
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
            <div className="space-y-2">
                <div className="flex gap-2 items-start flex-wrap">
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
                                <span className="flex items-center gap-2">
                                    Create in paused state
                                    <Tooltip
                                        title={
                                            "If selected, the Batch Exporter will be created but will be 'paused' allowing you to resumed it at a later date."
                                        }
                                    >
                                        <IconInfo className=" text-lg text-muted-alt" />
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

export function BatchExportsEditModel({
    isNew,
    batchExportConfigForm,
    setShowEditor,
    showEditor,
    selectedModel,
    setSelectedModel,
    tables,
    setQuery,
    query,
}: {
    isNew: boolean
    batchExportConfigForm: BatchExportConfigurationForm
    query: HogQLQuery
}): JSX.Element {
    return (
        <>
            {!showEditor ? (
                <>
                    <div className="space-y-2">

                        <div className="flex items-center justify-end gap-2">
                            <div className="flex-1 space-y-2">
                                <h2 className="mb-0">Model</h2>
                                <p>
                                    A model defines the data that will be exported by quering a PostHog table. Select the
                                    PostHog table to query from the dropdown below and optionally edit the query used to select
                                    data from it.
                                </p>
                            </div>

                            <LemonButton type="secondary" onClick={() => setShowEditor(true)}>
                                Edit query
                            </LemonButton>

                        </div>
                        <LemonField name="model">
                            <LemonSelect
                                options={tables.map((table) => ({
                                    value: table.name,
                                    label: table.id,
                                }))}
                                value={selectedModel}
                                onSelect={(newValue) => {
                                    setSelectedModel(newValue)
                                }}
                            />
                        </LemonField>

                        <DatabaseTable
                            table={selectedModel ? selectedModel : 'events'}
                            tables={tables}
                            inEditSchemaMode={false}
                        />
                    </div>
                </>
            ) : (
                <>
                    <div className="flex items-center justify-end gap-2">
                        <div className="flex-1 space-y-2">
                            <h2 className="mb-0">Model</h2>
                            <p>
                                A model defines the data that will be exported by quering a PostHog table. Select the
                                PostHog table to query from the dropdown below and optionally edit the query used to select
                                data from it.
                            </p>
                        </div>

                        <LemonButton size="xsmall" type="secondary" onClick={() => setShowEditor(false)}>
                            Hide query editor
                        </LemonButton>

                    </div>
                    <div className="relative w-full flex flex-col gap-4 h-full">
                        <HogQLQueryEditor
                            query={query}
                            embedded
                        />

                    </div>
                </>
            )}
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
            <div className="space-y-2">
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
                                        { value: 'me-south-1', label: 'Middle East (Bahrain)' },
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
                        <LemonField name="prefix" label="Key prefix">
                            <LemonInput placeholder="e.g. posthog-events/" />
                        </LemonField>

                        <div className="flex gap-4">
                            <LemonField name="file_format" label="Format" className="flex-1">
                                <LemonSelect
                                    options={[
                                        { value: 'JSONLines', label: 'JSON lines' },
                                        { value: 'Parquet', label: 'Apache Parquet' },
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
                                <LemonSelect
                                    options={[
                                        { value: 'gzip', label: 'gzip' },
                                        { value: 'brotli', label: 'brotli' },
                                        { value: null, label: 'No compression' },
                                    ]}
                                />
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

                        <LemonField name="exclude_events" label="Events to exclude" className="flex-1">
                            <LemonInputSelect
                                mode="multiple"
                                allowCustomValues
                                options={[]}
                                placeholder="Input one or more events to exclude from the export (optional)"
                            />
                        </LemonField>
                        <LemonField name="include_events" label="Events to include" className="flex-1">
                            <LemonInputSelect
                                mode="multiple"
                                allowCustomValues
                                options={[]}
                                placeholder="Input one or more events to include in the export (optional)"
                            />
                        </LemonField>
                    </>
                ) : batchExportConfigForm.destination === 'Snowflake' ? (
                    <>
                        <LemonField name="user" label="User">
                            <LemonInput placeholder={isNew ? 'my-user' : 'Leave unchanged'} />
                        </LemonField>

                        <LemonField name="password" label="Password">
                            <LemonInput placeholder={isNew ? 'my-password' : 'Leave unchanged'} type="password" />
                        </LemonField>

                        <LemonField name="account" label="Account">
                            <LemonInput placeholder="my-account" />
                        </LemonField>

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

                        <LemonField name="exclude_events" label="Events to exclude" className="flex-1">
                            <LemonInputSelect
                                mode="multiple"
                                allowCustomValues
                                options={[]}
                                placeholder="Input one or more events to exclude from the export (optional)"
                            />
                        </LemonField>
                        <LemonField name="include_events" label="Events to include" className="flex-1">
                            <LemonInputSelect
                                mode="multiple"
                                allowCustomValues
                                options={[]}
                                placeholder="Input one or more events to include in the export (optional)"
                            />
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
                                        <span className="flex items-center gap-2">
                                            Does your Postgres instance have a self-signed SSL certificate?
                                            <Tooltip title="In most cases, Heroku and RDS users should check this.">
                                                <IconInfo className=" text-lg text-muted-alt" />
                                            </Tooltip>
                                        </span>
                                    }
                                    checked={!!value}
                                    onChange={onChange}
                                />
                            )}
                        </LemonField>

                        <LemonField name="exclude_events" label="Events to exclude" className="flex-1">
                            <LemonInputSelect
                                mode="multiple"
                                allowCustomValues
                                options={[]}
                                placeholder="Input one or more events to exclude from the export (optional)"
                            />
                        </LemonField>
                        <LemonField name="include_events" label="Events to include" className="flex-1">
                            <LemonInputSelect
                                mode="multiple"
                                allowCustomValues
                                options={[]}
                                placeholder="Input one or more events to include in the export (optional)"
                            />
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

                        <LemonField name="exclude_events" label="Events to exclude" className="flex-1">
                            <LemonInputSelect
                                mode="multiple"
                                allowCustomValues
                                options={[]}
                                placeholder="Input one or more events to exclude from the export (optional)"
                            />
                        </LemonField>
                        <LemonField name="include_events" label="Events to include" className="flex-1">
                            <LemonInputSelect
                                mode="multiple"
                                allowCustomValues
                                options={[]}
                                placeholder="Input one or more events to include in the export (optional)"
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
                                        <span className="flex items-center gap-2">
                                            Export 'properties', 'set', and 'set_once' fields as BigQuery JSON type
                                            <Tooltip title="If left unchecked, these fields will be sent as STRING type. This setting cannot be changed after batch export is created.">
                                                <IconInfo className=" text-lg text-muted-alt" />
                                            </Tooltip>
                                        </span>
                                    }
                                />
                            </LemonField>
                        ) : null}

                        <LemonField name="exclude_events" label="Events to exclude" className="flex-1">
                            <LemonInputSelect
                                mode="multiple"
                                allowCustomValues
                                options={[]}
                                placeholder="Input one or more events to exclude from the export (optional)"
                            />
                        </LemonField>
                        <LemonField name="include_events" label="Events to include" className="flex-1">
                            <LemonInputSelect
                                mode="multiple"
                                allowCustomValues
                                options={[]}
                                placeholder="Input one or more events to include in the export (optional)"
                            />
                        </LemonField>
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
                        <LemonField name="exclude_events" label="Events to exclude" className="flex-1">
                            <LemonInputSelect
                                mode="multiple"
                                allowCustomValues
                                options={[]}
                                placeholder="Input one or more events to exclude from the export (optional)"
                            />
                        </LemonField>
                        <LemonField name="include_events" label="Events to include" className="flex-1">
                            <LemonInputSelect
                                mode="multiple"
                                allowCustomValues
                                options={[]}
                                placeholder="Input one or more events to include in the export (optional)"
                            />
                        </LemonField>
                    </>
                ) : null}
            </div>
        </>
    )
}
