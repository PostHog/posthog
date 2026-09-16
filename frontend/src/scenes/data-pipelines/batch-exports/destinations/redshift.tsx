import { LemonBanner, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { LemonField } from 'lib/lemon-ui/LemonField'

import type { IntegrationType } from '~/types'

import { AWS_ONLY_REGION_OPTIONS, PERSON_PROPERTIES_EVENT_FIELD, validateBucketName } from './common'
import type { DestinationDefinition } from './types'

// Redshift is the only destination with a non-trivial form ↔ payload mapping.
// The COPY mode requires nested copy_inputs (s3_bucket, s3_key_prefix, region_name,
// authorization, bucket_credentials), which we flatten to top-level redshift_* fields
// in the form for editing and re-assemble on save.
//
// The two COPY credentials do different jobs: bucket_credentials is what PostHog writes the staged
// files with, authorization is what Redshift reads them back with. Either can be an aws-s3
// Integration id; authorization can also be the ARN of a role attached to the cluster.
type AuthorizationMode = 'SameConnection' | 'DifferentConnection' | 'IAMRole' | 'Credentials'

function buildBucketCredentials(formValues: Record<string, any>): number | Record<string, string> | undefined {
    if (typeof formValues.redshift_s3_integration_id === 'number') {
        return formValues.redshift_s3_integration_id
    }
    if (formValues.redshift_s3_bucket_aws_access_key_id && formValues.redshift_s3_bucket_aws_secret_access_key) {
        return {
            aws_access_key_id: formValues.redshift_s3_bucket_aws_access_key_id,
            aws_secret_access_key: formValues.redshift_s3_bucket_aws_secret_access_key,
        }
    }
    return undefined
}

function buildAuthorization(formValues: Record<string, any>): number | string | Record<string, string> | undefined {
    switch (formValues.authorization_mode as AuthorizationMode) {
        case 'SameConnection':
            return typeof formValues.redshift_s3_integration_id === 'number'
                ? formValues.redshift_s3_integration_id
                : undefined
        case 'DifferentConnection':
            return typeof formValues.redshift_authorization_integration_id === 'number'
                ? formValues.redshift_authorization_integration_id
                : undefined
        case 'IAMRole':
            return formValues.redshift_iam_role || undefined
        case 'Credentials':
            return formValues.redshift_aws_access_key_id && formValues.redshift_aws_secret_access_key
                ? {
                      aws_access_key_id: formValues.redshift_aws_access_key_id,
                      aws_secret_access_key: formValues.redshift_aws_secret_access_key,
                  }
                : undefined
    }
}

// Credentials the form cannot see (the API strips them from `config` on read) are left out of the
// payload entirely rather than sent blank. The backend merges a partial config over the stored one,
// so an omitted field keeps its value.
function buildCopyInputs(formValues: Record<string, any>): Record<string, any> {
    const copyInputs: Record<string, any> = {
        s3_bucket: formValues.redshift_s3_bucket,
        s3_key_prefix: formValues.redshift_s3_key_prefix,
        region_name: formValues.redshift_s3_bucket_region_name,
    }

    const bucketCredentials = buildBucketCredentials(formValues)
    if (bucketCredentials !== undefined) {
        copyInputs.bucket_credentials = bucketCredentials
    }

    const authorization = buildAuthorization(formValues)
    if (authorization !== undefined) {
        copyInputs.authorization = authorization
    }

    return copyInputs
}

const REDSHIFT_FORM_ONLY_FIELDS = [
    'mode',
    'authorization_mode',
    // copy_inputs is re-assembled from the flat redshift_* fields in COPY mode and must not be
    // carried over verbatim — otherwise switching a COPY export to INSERT leaks the stale object.
    'copy_inputs',
    'redshift_s3_bucket',
    'redshift_s3_key_prefix',
    'redshift_s3_bucket_region_name',
    'redshift_s3_integration_id',
    'redshift_s3_credentials_inline',
    'redshift_s3_bucket_aws_access_key_id',
    'redshift_s3_bucket_aws_secret_access_key',
    'redshift_authorization_integration_id',
    'redshift_iam_role',
    'redshift_aws_access_key_id',
    'redshift_aws_secret_access_key',
] as const

// New exports must store their credentials in Integrations. Exports created before integrations
// existed keep their inline credentials, detected by what deserialize found in the stored config.
function usesConnection(isNew: boolean, formValues: Record<string, any>): boolean {
    return isNew || !!formValues.integration_id
}

function usesS3Connection(isNew: boolean, formValues: Record<string, any>): boolean {
    return isNew || !formValues.redshift_s3_credentials_inline
}

// Only a plain Redshift connection stores its own endpoint. AWS ones mint temporary credentials for
// a cluster endpoint that stays on the export, so the export has to carry the host itself.
function connectionCarriesHost(connection: IntegrationType | null | undefined): boolean {
    return !!connection?.config?.host
}

export const redshiftDefinition: DestinationDefinition = {
    type: 'Redshift',
    usesIntegration: true,
    defaults: () => ({
        mode: 'COPY',
        authorization_mode: 'SameConnection',
        properties_data_type: 'super',
    }),
    requiredFields: ({ isNew, formValues, selectedIntegration }) => {
        const fields = ['database', 'schema', 'table_name']

        if (usesConnection(isNew, formValues)) {
            if (isNew) {
                fields.push('integration_id')
            }
            // Held back until a connection is picked: `integration_id` already blocks the save, and
            // flagging an endpoint we may not even need reads as a second, wrong problem.
            if (formValues.integration_id && !connectionCarriesHost(selectedIntegration)) {
                fields.push('host')
            }
        } else {
            fields.push('host')
        }

        if (formValues.mode === 'COPY') {
            // s3_key_prefix is intentionally not required: the backend defaults a missing prefix to
            // the bucket root, so leaving it blank is a valid choice, not an error.
            fields.push('redshift_s3_bucket', 'redshift_s3_bucket_region_name')

            if (usesS3Connection(isNew, formValues)) {
                fields.push('redshift_s3_integration_id')
            }

            if (formValues.authorization_mode === 'DifferentConnection') {
                fields.push('redshift_authorization_integration_id')
            } else if (formValues.authorization_mode === 'IAMRole') {
                fields.push('redshift_iam_role')
            }
        }

        return fields
    },
    // Mirrors the destination fields of RedshiftBatchExportInputs. The inline credential keys stay
    // allowlisted for grandfathered exports.
    // TODO: drop user/password once every export is integration-backed
    configKeys: [
        'database',
        'host',
        'port',
        'schema',
        'table_name',
        'properties_data_type',
        'mode',
        'copy_inputs',
        'user',
        'password',
    ],
    validate: (formValues) => {
        if (formValues.mode === 'COPY') {
            return { redshift_s3_bucket: validateBucketName(formValues.redshift_s3_bucket) }
        }
        return {}
    },
    serialize: (formValues) => {
        const config: Record<string, any> = {}
        for (const [key, value] of Object.entries(formValues)) {
            if ((REDSHIFT_FORM_ONLY_FIELDS as readonly string[]).includes(key)) {
                continue
            }
            config[key] = value
        }
        config.mode = formValues.mode
        // copy_inputs is rebuilt from the flat redshift_* fields in COPY mode and explicitly nulled
        // in INSERT mode — never carried over from the deserialized form state.
        config.copy_inputs = formValues.mode === 'COPY' ? buildCopyInputs(formValues) : null
        return config
    },
    deserialize: (config) => {
        const result: Record<string, any> = {
            // Exports created before COPY existed store no mode, and INSERT is what they run.
            mode: 'INSERT',
            ...config,
            authorization_mode: 'SameConnection',
        }
        const copyInputs = config.copy_inputs
        if (!copyInputs) {
            return result
        }

        result.redshift_s3_bucket = copyInputs.s3_bucket
        result.redshift_s3_key_prefix = copyInputs.s3_key_prefix
        result.redshift_s3_bucket_region_name = copyInputs.region_name
        result.redshift_s3_integration_id = undefined
        result.redshift_s3_bucket_aws_access_key_id = undefined
        result.redshift_s3_bucket_aws_secret_access_key = undefined
        result.redshift_authorization_integration_id = undefined
        result.redshift_iam_role = undefined
        result.redshift_aws_access_key_id = undefined
        result.redshift_aws_secret_access_key = undefined

        const bucketCredentials = copyInputs.bucket_credentials
        // Inline credentials come back as an empty object once the API strips them, so the shape of
        // what is stored — not its contents — is what says whether this export predates connections.
        result.redshift_s3_credentials_inline = bucketCredentials !== undefined && typeof bucketCredentials !== 'number'
        if (typeof bucketCredentials === 'number') {
            result.redshift_s3_integration_id = bucketCredentials
        } else if (bucketCredentials) {
            result.redshift_s3_bucket_aws_access_key_id = bucketCredentials.aws_access_key_id
            result.redshift_s3_bucket_aws_secret_access_key = bucketCredentials.aws_secret_access_key
        }

        const authorization = copyInputs.authorization
        if (typeof authorization === 'number') {
            result.redshift_authorization_integration_id = authorization
            result.authorization_mode = authorization === bucketCredentials ? 'SameConnection' : 'DifferentConnection'
        } else if (typeof authorization === 'string') {
            result.authorization_mode = 'IAMRole'
            result.redshift_iam_role = authorization
        } else if (authorization) {
            result.authorization_mode = 'Credentials'
            result.redshift_aws_access_key_id = authorization.aws_access_key_id
            result.redshift_aws_secret_access_key = authorization.aws_secret_access_key
        }

        return result
    },
    eventTableOverrides: { teamIdHogql: 'toInt32(team_id)' },
    eventTableExtraFields: { ...PERSON_PROPERTIES_EVENT_FIELD },
    Fields: function RedshiftFields({ isNew, formValues, selectedIntegration }) {
        const useConnection = usesConnection(isNew, formValues)
        const useS3Connection = usesS3Connection(isNew, formValues)
        // Until a connection is picked we cannot tell which kind it is, so we keep asking.
        const showHost = !useConnection || !connectionCarriesHost(selectedIntegration)

        // "Credentials" is never offered to a new export. It stays reachable while an export still
        // stores inline keys, so an accidental switch away from it can be undone.
        const allowInlineAuthorizationKeys = !useS3Connection || formValues.authorization_mode === 'Credentials'
        const authorizationOptions = [
            ...(useS3Connection ? [{ value: 'SameConnection', label: 'Use the S3 connection above' }] : []),
            {
                value: 'DifferentConnection',
                label: useS3Connection ? 'Use a different S3 connection' : 'Use an S3 connection',
            },
            { value: 'IAMRole', label: 'Use an IAM role attached to the cluster' },
            ...(allowInlineAuthorizationKeys ? [{ value: 'Credentials', label: 'Use AWS access keys' }] : []),
        ]

        return (
            <>
                {useConnection ? (
                    <LemonField name="integration_id" label="Connection">
                        {({ value, onChange }) => (
                            <IntegrationChoice integration="aws-redshift" value={value} onChange={onChange} />
                        )}
                    </LemonField>
                ) : (
                    <>
                        <LemonBanner type="warning">
                            PostHog is moving Redshift batch exports to saved connections. This export will be migrated
                            automatically.
                        </LemonBanner>

                        <LemonField name="user" label="User">
                            <LemonInput placeholder="Leave unchanged" />
                        </LemonField>

                        <LemonField name="password" label="Password">
                            <LemonInput placeholder="Leave unchanged" type="password" />
                        </LemonField>
                    </>
                )}

                {showHost && (
                    <>
                        <LemonField name="host" label="Host">
                            <LemonInput placeholder="my-host" />
                        </LemonField>

                        <LemonField name="port" label="Port" showOptional>
                            <LemonInput placeholder="5439" type="number" min="0" max="65535" />
                        </LemonField>
                    </>
                )}

                <LemonField name="database" label="Database">
                    <LemonInput placeholder="my-database" />
                </LemonField>

                <LemonField name="schema" label="Schema">
                    <LemonInput placeholder="public" />
                </LemonField>

                <LemonField name="table_name" label="Table name">
                    <LemonInput placeholder="events" />
                </LemonField>

                <LemonField
                    name="properties_data_type"
                    label="Semi-structured data type"
                    info={
                        <>
                            Different PostHog models have semi-structured data fields in them, like "events.properties".
                            We can export these fields to Redshift as a "SUPER" type column, or a "VARCHAR" column. We
                            recommend "SUPER" over "VARCHAR" as "VARCHAR" has a strict length limit that applies on the
                            entire document, whereas with "SUPER" the limit applies on each value in the document.
                        </>
                    }
                >
                    <LemonSelect
                        options={[
                            { value: 'varchar', label: 'VARCHAR(65535)' },
                            { value: 'super', label: 'SUPER' },
                        ]}
                    />
                </LemonField>

                <LemonField
                    name="mode"
                    label="Command"
                    className="flex-1"
                    info={
                        <>
                            Choose the SQL command used by the batch export. "COPY" has the best performance but
                            requires an S3 bucket we can connect to. "INSERT" performs worse but without any additional
                            requirements.
                        </>
                    }
                >
                    <LemonSelect
                        options={[
                            { value: 'COPY', label: 'COPY' },
                            { value: 'INSERT', label: 'INSERT' },
                        ]}
                    />
                </LemonField>

                {formValues.mode === 'COPY' && (
                    <>
                        <p className="text-xs text-muted mt-1">
                            COPY loads data through an S3 bucket. PostHog stages the export files there, then tells
                            Redshift to copy them into your table.
                        </p>

                        <div className="flex gap-4">
                            <LemonField name="redshift_s3_bucket" label="S3 bucket name" className="flex-1">
                                <LemonInput placeholder="e.g. my-bucket" />
                            </LemonField>
                            <LemonField
                                name="redshift_s3_bucket_region_name"
                                label="S3 bucket region"
                                className="flex-1"
                            >
                                <LemonSelect options={AWS_ONLY_REGION_OPTIONS} />
                            </LemonField>
                        </div>

                        <LemonField name="redshift_s3_key_prefix" label="S3 key prefix" className="flex-1">
                            <LemonInput placeholder="e.g. /posthog-copy-files" />
                        </LemonField>

                        {useS3Connection ? (
                            <LemonField
                                name="redshift_s3_integration_id"
                                label="S3 connection"
                                info="The credentials PostHog uses to stage export files in the bucket."
                            >
                                {({ value, onChange }) => (
                                    <IntegrationChoice integration="aws-s3" value={value} onChange={onChange} />
                                )}
                            </LemonField>
                        ) : (
                            <>
                                <LemonBanner type="warning">
                                    PostHog is moving the S3 staging credentials to saved connections. This export will
                                    be migrated automatically.
                                </LemonBanner>

                                <div className="flex gap-4">
                                    <LemonField
                                        name="redshift_s3_bucket_aws_access_key_id"
                                        label="AWS Access Key ID"
                                        className="flex-1"
                                    >
                                        <LemonInput placeholder="Leave unchanged" autoComplete="off" />
                                    </LemonField>

                                    <LemonField
                                        name="redshift_s3_bucket_aws_secret_access_key"
                                        label="AWS Secret Access Key"
                                        className="flex-1"
                                    >
                                        <LemonInput
                                            placeholder="Leave unchanged"
                                            type="password"
                                            autoComplete="new-password"
                                        />
                                    </LemonField>
                                </div>
                            </>
                        )}

                        <LemonField
                            name="authorization_mode"
                            label="How Redshift reads staged files"
                            className="flex-1"
                            info="PostHog writes the staged files. Redshift then needs its own access to read them back."
                        >
                            <LemonSelect options={authorizationOptions} />
                        </LemonField>

                        {formValues.authorization_mode === 'DifferentConnection' && (
                            <LemonField name="redshift_authorization_integration_id" label="S3 connection for Redshift">
                                {({ value, onChange }) => (
                                    <IntegrationChoice integration="aws-s3" value={value} onChange={onChange} />
                                )}
                            </LemonField>
                        )}

                        {formValues.authorization_mode === 'IAMRole' && (
                            <LemonField name="redshift_iam_role" label="IAM Role ARN" className="flex-1">
                                <LemonInput placeholder="e.g. arn:aws:iam::<aws-account-id>:role/<role-name>" />
                            </LemonField>
                        )}

                        {formValues.authorization_mode === 'Credentials' && (
                            <div className="flex gap-4">
                                <LemonField
                                    name="redshift_aws_access_key_id"
                                    label="AWS Access Key ID"
                                    className="flex-1"
                                >
                                    <LemonInput placeholder="Leave unchanged" autoComplete="off" />
                                </LemonField>

                                <LemonField
                                    name="redshift_aws_secret_access_key"
                                    label="AWS Secret Access Key"
                                    className="flex-1"
                                >
                                    <LemonInput
                                        placeholder="Leave unchanged"
                                        type="password"
                                        autoComplete="new-password"
                                    />
                                </LemonField>
                            </div>
                        )}
                    </>
                )}
            </>
        )
    },
}
