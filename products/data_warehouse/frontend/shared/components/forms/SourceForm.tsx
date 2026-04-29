import { useActions, useValues } from 'kea'
import { FieldName, Form, Group } from 'kea-forms'
import React, { useEffect, useState } from 'react'

import {
    LemonButton,
    LemonDivider,
    LemonFileInput,
    LemonInput,
    LemonSelect,
    LemonSkeleton,
    LemonSwitch,
    LemonTag,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { SourceConfig, SourceFieldConfig } from '~/queries/schema/schema-general'

import { availableSourcesLogic } from '../../../scenes/NewSourceScene/availableSourcesLogic'
import { SSH_FIELD, sourceWizardLogic } from '../../../scenes/NewSourceScene/sourceWizardLogic'
import { GitHubRepositorySelector } from './GitHubRepositorySelector'
import { SourceIntegrationChoice } from './IntegrationChoice'
import { parseConnectionStringForSource } from './parsers'

export interface SourceFormProps {
    sourceConfig: SourceConfig
    showPrefix?: boolean
    showDescription?: boolean
    showAccessMethodSelector?: boolean
    jobInputs?: Record<string, any>
    initialAccessMethod?: 'warehouse' | 'direct'
    setSourceConfigValue?: (key: FieldName, value: any) => void
}

export function SourceAccessMethodSelector({
    value,
    onChange,
}: {
    value: 'warehouse' | 'direct'
    onChange: (value: 'warehouse' | 'direct') => void
}): JSX.Element {
    return (
        <LemonField.Pure label="How should PostHog query this source?">
            <LemonRadio
                data-attr="postgres-access-method"
                value={value}
                onChange={(newValue) => onChange(newValue as 'warehouse' | 'direct')}
                options={[
                    {
                        value: 'warehouse',
                        label: (
                            <div>
                                <div>Sync to warehouse</div>
                                <div className="text-xs text-secondary">
                                    Sync selected tables into PostHog-managed storage for querying.
                                </div>
                            </div>
                        ),
                    },
                    {
                        value: 'direct',
                        label: (
                            <div>
                                <div className="flex items-center gap-2">
                                    <span>Query directly</span>
                                    <LemonTag type="warning" size="small">
                                        BETA
                                    </LemonTag>
                                </div>
                                <div className="text-xs text-secondary">
                                    Run queries live against this Postgres connection. Data from this source can&apos;t
                                    be joined with PostHog data.
                                </div>
                            </div>
                        ),
                    },
                ]}
            />
        </LemonField.Pure>
    )
}

export const sourceFieldToElement = (
    field: SourceFieldConfig,
    sourceConfig: SourceConfig,
    lastValue?: any,
    isUpdateMode?: boolean
): JSX.Element => {
    // It doesn't make sense for this to show on an update to an existing connection since we likely just want to change
    // a field or two. There is also some divergence in creates vs. updates that make this a bit more complex to handle.
    if (field.type === 'text' && field.name === 'connection_string') {
        if (isUpdateMode) {
            return <React.Fragment key={field.name} />
        }
        return (
            <React.Fragment key={field.name}>
                <LemonField name={field.name} label={field.label}>
                    {({ onChange }) => (
                        <LemonInput
                            key={field.name}
                            className="ph-connection-string"
                            data-attr={field.name}
                            placeholder={field.placeholder}
                            type="text"
                            onChange={(updatedConnectionString) => {
                                onChange(updatedConnectionString)
                                const { isValid, fields } = parseConnectionStringForSource(
                                    sourceConfig.name,
                                    updatedConnectionString
                                )

                                if (isValid) {
                                    for (const { path, value } of fields) {
                                        sourceWizardLogic.actions.setSourceConnectionDetailsValue(
                                            ['payload', ...path],
                                            value
                                        )
                                    }
                                }
                            }}
                        />
                    )}
                </LemonField>
                <LemonDivider />
            </React.Fragment>
        )
    }

    if (field.type === 'switch-group') {
        const enabled = !!lastValue?.[field.name]?.enabled || lastValue?.[field.name]?.enabled === 'True'
        return (
            <LemonField key={field.name} name={[field.name, 'enabled']} label={field.label}>
                {({ value, onChange }) => {
                    const isEnabled = value === undefined || value === null || value === 'False' ? enabled : value
                    return (
                        <>
                            {!!field.caption && <p className="mb-0">{field.caption}</p>}
                            <LemonSwitch checked={isEnabled} onChange={onChange} />
                            {isEnabled && (
                                <Group name={field.name}>
                                    {field.fields.map((field) =>
                                        sourceFieldToElement(field, sourceConfig, lastValue?.[field.name])
                                    )}
                                </Group>
                            )}
                        </>
                    )
                }}
            </LemonField>
        )
    }

    if (field.type === 'select') {
        const hasOptionFields = !!field.options.filter((n) => (n.fields?.length ?? 0) > 0).length

        const getOptions = (value: any): JSX.Element[] | undefined =>
            field.options
                .find((n) => n.value === (value ?? field.defaultValue))
                ?.fields?.map((optionField) =>
                    sourceFieldToElement(optionField, sourceConfig, lastValue?.[optionField.name])
                )

        return (
            <LemonField
                key={field.name}
                name={hasOptionFields ? [field.name, 'selection'] : field.name}
                label={field.label}
            >
                {({ value, onChange }) => (
                    <>
                        <LemonSelect
                            options={field.options}
                            value={
                                (value === undefined || value === null ? lastValue?.[field.name] : value) ||
                                field.defaultValue
                            }
                            onChange={onChange}
                        />
                        <Group name={field.name}>{getOptions(value)}</Group>
                    </>
                )}
            </LemonField>
        )
    }

    if (field.type === 'textarea') {
        return (
            <LemonField key={field.name} name={field.name} label={field.label}>
                {({ value, onChange }) => (
                    <LemonTextArea
                        className="ph-ignore-input"
                        data-attr={field.name}
                        placeholder={field.placeholder}
                        minRows={4}
                        value={value || ''}
                        onChange={onChange}
                    />
                )}
            </LemonField>
        )
    }

    if (field.type === 'oauth') {
        return (
            <LemonField key={field.name} name={field.name} label={field.label}>
                {({ value, onChange }) => (
                    <SourceIntegrationChoice
                        key={field.name}
                        sourceConfig={sourceConfig}
                        value={value}
                        onChange={onChange}
                        integration={field.kind}
                        schema={field.requiredScopes ? { requiredScopes: field.requiredScopes } : undefined}
                    />
                )}
            </LemonField>
        )
    }

    if (field.type === 'file-upload') {
        return (
            <LemonField key={field.name} name={field.name} label={field.label}>
                {({ value, onChange }) => (
                    <div className="bg-fill-input p-2 border rounded-[var(--radius)]">
                        <LemonFileInput
                            value={value}
                            accept={field.fileFormat.format}
                            multiple={false}
                            onChange={onChange}
                        />
                    </div>
                )}
            </LemonField>
        )
    }

    if (field.type === 'ssh-tunnel') {
        return sourceFieldToElement(
            { ...SSH_FIELD, name: field.name, label: field.label },
            sourceConfig,
            lastValue,
            isUpdateMode
        )
    }

    if (field.type === 'text' && field.name === 'repository' && sourceConfig.name === 'Github') {
        // Special case, this is the GitHub repository field
        return <GitHubRepositorySelector key={field.name} />
    }

    return (
        <LemonField
            key={field.name}
            name={field.name}
            label={field.label}
            help={field.caption ? <LemonMarkdown className="text-xs">{field.caption}</LemonMarkdown> : undefined}
        >
            {({ value, onChange }) => (
                <LemonInput
                    className="ph-ignore-input"
                    data-attr={field.name}
                    placeholder={field.placeholder}
                    type={field.type as 'text'}
                    value={value || ''}
                    onChange={onChange}
                />
            )}
        </LemonField>
    )
}

function CDCRequirementsPanel(): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    return (
        <div className="rounded border border-border p-3">
            <button
                type="button"
                className="flex items-center text-xs text-secondary hover:text-default cursor-pointer w-full"
                onClick={() => setExpanded((v) => !v)}
            >
                <span className="mr-2">{expanded ? '▾' : '▸'}</span>
                <span>What your database needs for CDC</span>
            </button>
            {expanded && (
                <div className="mt-3 text-xs space-y-2">
                    <p className="m-0">
                        PostgreSQL 13+ with logical replication enabled. Typical setup on your server:
                    </p>
                    <ul className="list-disc ml-5 space-y-1 m-0">
                        <li>
                            <code>wal_level = logical</code> (requires a server restart). On RDS, set{' '}
                            <code>rds.logical_replication = 1</code>.
                        </li>
                        <li>
                            <code>max_replication_slots</code> and <code>max_wal_senders</code> with at least one free
                            slot for PostHog. Postgres' defaults (10) are plenty unless other consumers share the same
                            database.
                        </li>
                        <li>
                            Database user with <code>REPLICATION</code> (
                            <code>ALTER USER &lt;user&gt; WITH REPLICATION</code>) — or, on AWS RDS, membership in{' '}
                            <code>rds_replication</code>. Required for both PostHog-managed and self-managed modes;
                            PostHog creates and reads the replication slot either way.
                        </li>
                        <li>
                            <strong>PostHog-managed mode</strong> additionally needs ownership of the synced tables (or
                            a superuser) so PostHog can run <code>CREATE PUBLICATION</code>. In{' '}
                            <strong>self-managed mode</strong> the owner creates just the publication once — PostHog
                            connects with a user that only needs <code>SELECT</code> on the tables and{' '}
                            <code>REPLICATION</code>.
                        </li>
                        <li>Every table you want to sync must have a primary key.</li>
                        <li>
                            SSL/TLS is required — connect over a public endpoint with <code>sslmode=require</code>.
                        </li>
                    </ul>
                    <p className="m-0 text-secondary">
                        Click "Check database prerequisites" below to verify your configuration against a live
                        connection.
                    </p>
                </div>
            )}
        </div>
    )
}

function CDCPrerequisitesCheck(): JSX.Element {
    const {
        sourceConnectionDetails,
        sourceConnectionDetailsValidationErrors,
        cdcPrereqsCheckResult,
        cdcPrereqsCheckResultLoading,
    } = useValues(sourceWizardLogic)
    const { checkCdcPrereqs, touchAllSourceConnectionDetailsFields } = useActions(sourceWizardLogic)

    const hasFormErrors = (errs: any): boolean => {
        if (!errs) {
            return false
        }
        if (typeof errs === 'string') {
            return errs.length > 0
        }
        if (Array.isArray(errs)) {
            return errs.some(hasFormErrors)
        }
        if (typeof errs === 'object') {
            return Object.values(errs).some(hasFormErrors)
        }
        return false
    }

    const onClick = (): void => {
        if (hasFormErrors(sourceConnectionDetailsValidationErrors)) {
            touchAllSourceConnectionDetailsFields()
            lemonToast.error('Please fill in all required connection fields before checking prerequisites.')
            return
        }
        checkCdcPrereqs()
    }

    const checkedManagementMode = (sourceConnectionDetails?.payload?.cdc_management_mode || 'posthog') as
        | 'posthog'
        | 'self_managed'

    return (
        <div>
            <LemonButton type="secondary" onClick={onClick} loading={cdcPrereqsCheckResultLoading}>
                Check database prerequisites
            </LemonButton>
            {cdcPrereqsCheckResult && (
                <LemonBanner type={cdcPrereqsCheckResult.valid ? 'success' : 'error'} className="mt-2">
                    {cdcPrereqsCheckResult.valid ? (
                        <>
                            <p className="m-0">Your database is ready for CDC.</p>
                            {checkedManagementMode === 'self_managed' && (
                                <p className="m-0 text-xs mt-1">
                                    After you pick your tables in the next step, we'll show you the{' '}
                                    <code>CREATE PUBLICATION</code> statement to run as the table owner. PostHog creates
                                    the replication slot itself.
                                </p>
                            )}
                        </>
                    ) : (
                        <>
                            <p className="font-semibold mb-1">Some prerequisites are not met:</p>
                            <ul className="list-disc ml-5 mb-0 text-sm">
                                {cdcPrereqsCheckResult.errors.map((err: string, i: number) => (
                                    <li key={i}>{err}</li>
                                ))}
                            </ul>
                        </>
                    )}
                </LemonBanner>
            )}
        </div>
    )
}

function CDCConfigSection(): JSX.Element {
    // showAdvanced is purely local UI toggle — not a form field
    const [showAdvanced, setShowAdvanced] = React.useState(false)

    return (
        <Group name="payload">
            <div className="space-y-4 mt-4">
                <LemonField name="cdc_enabled">
                    {({ value: cdcEnabled, onChange }) => (
                        <div
                            className={`rounded border p-4 ${
                                cdcEnabled
                                    ? 'border-success/40 bg-success-highlight/40'
                                    : 'border-success/40 bg-success-highlight/20'
                            }`}
                        >
                            <div className="flex items-start justify-between gap-4">
                                <div>
                                    <div className="flex items-center gap-2 mb-1">
                                        <h4 className="mb-0 text-base font-semibold">Change data capture (CDC)</h4>
                                        <LemonTag type="success">Recommended</LemonTag>
                                    </div>
                                    <p className="text-sm text-secondary mb-2">
                                        Real-time sync via PostgreSQL logical replication. Captures inserts, updates,
                                        and <strong>deletes</strong> — the other sync modes can't. No full table scans
                                        and no reliance on an <code>updated_at</code> field.
                                    </p>
                                </div>
                                <LemonSwitch checked={!!cdcEnabled} onChange={onChange} />
                            </div>
                            <LemonDivider className="my-3" />
                            <CDCRequirementsPanel />
                            <div className="mt-2">
                                <CDCPrerequisitesCheck />
                            </div>
                        </div>
                    )}
                </LemonField>

                <LemonField name="cdc_enabled">
                    {({ value: cdcEnabled }) =>
                        cdcEnabled ? (
                            <>
                                <LemonField name="cdc_management_mode" label="Slot management">
                                    {({ value: managementMode, onChange }) => (
                                        <LemonRadio
                                            value={managementMode || 'posthog'}
                                            onChange={onChange}
                                            options={[
                                                {
                                                    value: 'posthog',
                                                    label: (
                                                        <div>
                                                            <div>PostHog-managed</div>
                                                            <div className="text-xs text-secondary">
                                                                PostHog creates and manages the replication slot and
                                                                publication. Requires a database user with REPLICATION
                                                                privileges.
                                                            </div>
                                                        </div>
                                                    ),
                                                },
                                                {
                                                    value: 'self_managed',
                                                    label: (
                                                        <div>
                                                            <div>Self-managed</div>
                                                            <div className="text-xs text-secondary">
                                                                You (or your DBA) create just the publication once as
                                                                the table owner. PostHog creates and manages the
                                                                replication slot itself, and still needs REPLICATION (or
                                                                rds_replication on RDS) plus SELECT on the synced
                                                                tables.
                                                            </div>
                                                        </div>
                                                    ),
                                                },
                                            ]}
                                        />
                                    )}
                                </LemonField>

                                <LemonField name="cdc_management_mode">
                                    {({ value: managementMode }) =>
                                        managementMode === 'self_managed' ? (
                                            <div className="space-y-4">
                                                <LemonField name="cdc_publication_name" label="Publication name">
                                                    {({ value, onChange }) => (
                                                        <LemonInput
                                                            placeholder="posthog_pub"
                                                            value={value || ''}
                                                            onChange={onChange}
                                                        />
                                                    )}
                                                </LemonField>
                                                <LemonBanner type="info">
                                                    <p className="font-semibold mb-1">Setup SQL comes next</p>
                                                    <p className="text-xs m-0">
                                                        After you pick the tables to sync, we'll show you a{' '}
                                                        <code>CREATE PUBLICATION</code> statement to run as the table
                                                        owner. PostHog creates and manages the replication slot itself.
                                                    </p>
                                                </LemonBanner>
                                            </div>
                                        ) : (
                                            <></>
                                        )
                                    }
                                </LemonField>

                                <div>
                                    <button
                                        type="button"
                                        className="text-xs text-secondary hover:text-default cursor-pointer"
                                        onClick={() => setShowAdvanced((v) => !v)}
                                    >
                                        {showAdvanced ? '▾' : '▸'} Advanced settings
                                    </button>

                                    {showAdvanced && (
                                        <div className="space-y-4 mt-3 pl-3 border-l-2 border-border">
                                            <LemonField name="cdc_management_mode">
                                                {({ value: managementMode }) =>
                                                    (managementMode || 'posthog') === 'posthog' ? (
                                                        <LemonField
                                                            name="cdc_auto_drop_slot"
                                                            label="Automatic slot protection"
                                                            info="When enabled, PostHog will automatically drop the replication slot if WAL lag exceeds the critical threshold, preventing disk exhaustion on your database."
                                                        >
                                                            {({ value: autoDropSlot, onChange }) => (
                                                                <>
                                                                    <LemonSwitch
                                                                        checked={autoDropSlot ?? true}
                                                                        onChange={onChange}
                                                                    />
                                                                    {(autoDropSlot ?? true) && (
                                                                        <div className="space-y-4 mt-4">
                                                                            <LemonField
                                                                                name="cdc_lag_warning_threshold_mb"
                                                                                label="WAL lag warning threshold (MB)"
                                                                                info="PostHog will log a warning when replication slot lag exceeds this value."
                                                                            >
                                                                                {({
                                                                                    value: warnVal,
                                                                                    onChange: warnOnChange,
                                                                                }) => (
                                                                                    <LemonInput
                                                                                        type="number"
                                                                                        value={warnVal ?? 1024}
                                                                                        onChange={warnOnChange}
                                                                                        min={1}
                                                                                    />
                                                                                )}
                                                                            </LemonField>
                                                                            <LemonField
                                                                                name="cdc_lag_critical_threshold_mb"
                                                                                label="WAL lag critical threshold (MB)"
                                                                                info="PostHog will drop the replication slot when lag exceeds this value (requires automatic slot protection to be enabled)."
                                                                            >
                                                                                {({
                                                                                    value: critVal,
                                                                                    onChange: critOnChange,
                                                                                }) => (
                                                                                    <LemonInput
                                                                                        type="number"
                                                                                        value={critVal ?? 10240}
                                                                                        onChange={critOnChange}
                                                                                        min={1}
                                                                                    />
                                                                                )}
                                                                            </LemonField>
                                                                        </div>
                                                                    )}
                                                                </>
                                                            )}
                                                        </LemonField>
                                                    ) : (
                                                        <></>
                                                    )
                                                }
                                            </LemonField>
                                        </div>
                                    )}
                                </div>
                            </>
                        ) : (
                            <></>
                        )
                    }
                </LemonField>
            </div>
        </Group>
    )
}

export default function SourceFormContainer(props: SourceFormProps): JSX.Element {
    return (
        <Form logic={sourceWizardLogic} formKey="sourceConnectionDetails" enableFormOnSubmit>
            <SourceFormComponent {...props} />
        </Form>
    )
}

export function SourceFormComponent({
    sourceConfig,
    showPrefix = true,
    showDescription,
    showAccessMethodSelector = true,
    jobInputs,
    initialAccessMethod,
    setSourceConfigValue,
}: SourceFormProps): JSX.Element {
    const { availableSources, availableSourcesLoading } = useValues(availableSourcesLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    // Default showDescription to same as showPrefix for backward compatibility
    const shouldShowDescription = showDescription ?? showPrefix
    const [selectedAccessMethod, setSelectedAccessMethod] = React.useState<'warehouse' | 'direct'>(
        initialAccessMethod ?? 'warehouse'
    )
    const isPostgresDirectQuery =
        sourceConfig.name === 'Postgres' &&
        !!featureFlags[FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY] &&
        selectedAccessMethod === 'direct'

    useEffect(() => {
        if (initialAccessMethod) {
            setSelectedAccessMethod(initialAccessMethod)
        }
    }, [initialAccessMethod])

    useEffect(() => {
        if (jobInputs && setSourceConfigValue) {
            for (const input of Object.keys(jobInputs || {})) {
                setSourceConfigValue(['payload', input], jobInputs[input])
            }
        }
    }, [JSON.stringify(jobInputs), setSourceConfigValue, jobInputs])

    const isUpdateMode = !!setSourceConfigValue

    if (availableSourcesLoading || !availableSources) {
        return <LemonSkeleton />
    }

    return (
        <div className="space-y-4 ph-no-capture">
            {!isUpdateMode &&
                sourceConfig.name === 'Postgres' &&
                showAccessMethodSelector &&
                featureFlags[FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY] && (
                    <>
                        <LemonField name="access_method">
                            {({ value, onChange }) => (
                                <SourceAccessMethodSelector
                                    value={(value as 'warehouse' | 'direct' | undefined) || selectedAccessMethod}
                                    onChange={(nextValue) => {
                                        setSelectedAccessMethod(nextValue)
                                        onChange(nextValue)
                                    }}
                                />
                            )}
                        </LemonField>
                        <LemonDivider />
                    </>
                )}
            {isPostgresDirectQuery && (
                <LemonField
                    name="prefix"
                    label="Name"
                    help="Required. This name is shown in the query editor when selecting a Postgres connection."
                >
                    {({ value, onChange }) => {
                        const validationError = value && !value.trim() ? 'Name cannot be empty whitespace' : ''
                        const displayValue = value?.trim() || 'My Postgres database'

                        return (
                            <>
                                <LemonInput
                                    className="ph-ignore-input"
                                    data-attr="prefix"
                                    placeholder="e.g. Production database"
                                    value={value}
                                    onChange={onChange}
                                    status={validationError ? 'danger' : undefined}
                                />
                                {validationError && <p className="text-danger text-xs mt-1">{validationError}</p>}
                                <p className="mb-0">
                                    Shown as: <strong>{displayValue} (Postgres)</strong>
                                </p>
                            </>
                        )
                    }}
                </LemonField>
            )}
            {shouldShowDescription && (
                <LemonField
                    name="description"
                    label="Description (optional)"
                    help="A description to help you identify this source, e.g. 'Production EU database' or 'Billing Stripe account'."
                >
                    {({ value, onChange }) => (
                        <LemonInput
                            className="ph-ignore-input"
                            data-attr="description"
                            placeholder="e.g. Production database"
                            value={value || ''}
                            onChange={onChange}
                        />
                    )}
                </LemonField>
            )}
            <Group name="payload">
                {availableSources[sourceConfig.name].fields
                    .filter((field) => !(isPostgresDirectQuery && field.type === 'ssh-tunnel'))
                    .map((field) => sourceFieldToElement(field, sourceConfig, jobInputs?.[field.name], isUpdateMode))}
            </Group>
            {!isUpdateMode &&
                sourceConfig.name === 'Postgres' &&
                featureFlags[FEATURE_FLAGS.DWH_POSTGRES_CDC] &&
                selectedAccessMethod === 'warehouse' && <CDCConfigSection />}
            {showPrefix && !isPostgresDirectQuery && (
                <LemonField
                    name="prefix"
                    label="Table prefix (optional)"
                    help="Use only letters, numbers, and underscores. Must start with a letter or underscore."
                >
                    {({ value, onChange }) => {
                        const cleaned = value ? value.trim().replace(/^_+|_+$/g, '') : ''
                        let validationError = ''

                        if (cleaned && !/^[A-Za-z_][A-Za-z0-9_]*$/.test(cleaned)) {
                            validationError =
                                'Prefix must contain only letters, numbers, and underscores, and start with a letter or underscore'
                        } else if (value && !cleaned) {
                            validationError =
                                value.trim().length === 0
                                    ? 'Prefix cannot be empty whitespace'
                                    : 'Prefix cannot consist of only underscores'
                        }

                        const displayValue = value ? value.trim().replace(/^_+|_+$/g, '') : ''
                        const tableName = displayValue
                            ? `${sourceConfig.name.toLowerCase()}.${displayValue}.table_name`
                            : `${sourceConfig.name.toLowerCase()}.table_name`
                        return (
                            <>
                                <LemonInput
                                    className="ph-ignore-input"
                                    data-attr="prefix"
                                    placeholder="internal"
                                    value={value}
                                    onChange={onChange}
                                    status={validationError ? 'danger' : undefined}
                                />
                                {validationError && <p className="text-danger text-xs mt-1">{validationError}</p>}
                                <p className="mb-0">
                                    Table name will look like:&nbsp;
                                    <strong>{tableName}</strong>
                                </p>
                            </>
                        )
                    }}
                </LemonField>
            )}
        </div>
    )
}
