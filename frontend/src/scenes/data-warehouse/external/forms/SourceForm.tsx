import { useValues } from 'kea'
import { FieldName, Form, Group } from 'kea-forms'
import React, { useEffect } from 'react'

import {
    LemonDivider,
    LemonFileInput,
    LemonInput,
    LemonSelect,
    LemonSkeleton,
    LemonSwitch,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { availableSourcesDataLogic } from 'scenes/data-warehouse/new/availableSourcesDataLogic'

import { SourceConfig, SourceFieldConfig } from '~/queries/schema/schema-general'

import { SSH_FIELD, sourceWizardLogic } from '../../new/sourceWizardLogic'
import { DataWarehouseIntegrationChoice } from './DataWarehouseIntegrationChoice'
import { GitHubRepositorySelector } from './GitHubRepositorySelector'
import { parseConnectionString } from './parseConnectionString'

export interface SourceFormProps {
    sourceConfig: SourceConfig
    showPrefix?: boolean
    showDescription?: boolean
    jobInputs?: Record<string, any>
    initialAccessMethod?: 'warehouse' | 'direct'
    setSourceConfigValue?: (key: FieldName, value: any) => void
}

const CONNECTION_STRING_DEFAULT_PORT: Record<string, number> = {
    Postgres: 5432,
    Redshift: 5439,
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
                                const { host, port, database, user, password, isValid } =
                                    parseConnectionString(updatedConnectionString)

                                if (isValid) {
                                    sourceWizardLogic.actions.setSourceConnectionDetailsValue(
                                        ['payload', 'database'],
                                        database || ''
                                    )
                                    sourceWizardLogic.actions.setSourceConnectionDetailsValue(
                                        ['payload', 'host'],
                                        host || ''
                                    )
                                    sourceWizardLogic.actions.setSourceConnectionDetailsValue(
                                        ['payload', 'user'],
                                        user || ''
                                    )
                                    sourceWizardLogic.actions.setSourceConnectionDetailsValue(
                                        ['payload', 'port'],
                                        port || CONNECTION_STRING_DEFAULT_PORT[sourceConfig.name]
                                    )
                                    sourceWizardLogic.actions.setSourceConnectionDetailsValue(
                                        ['payload', 'password'],
                                        password || ''
                                    )
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
                    <DataWarehouseIntegrationChoice
                        key={field.name}
                        sourceConfig={sourceConfig}
                        value={value}
                        onChange={onChange}
                        integration={field.kind}
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
    jobInputs,
    initialAccessMethod,
    setSourceConfigValue,
}: SourceFormProps): JSX.Element {
    const { availableSources, availableSourcesLoading } = useValues(availableSourcesDataLogic)
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
        <div className="deprecated-space-y-4">
            {!isUpdateMode &&
                sourceConfig.name === 'Postgres' &&
                featureFlags[FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY] && (
                    <LemonField name="access_method" label="How should PostHog query this source?">
                        {({ value, onChange }) => (
                            <LemonRadio
                                data-attr="postgres-access-method"
                                value={(value as 'warehouse' | 'direct' | undefined) || selectedAccessMethod}
                                onChange={(newValue) => {
                                    const nextValue = newValue as 'warehouse' | 'direct'
                                    setSelectedAccessMethod(nextValue)
                                    onChange(nextValue)
                                }}
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
                                                <div>Query directly</div>
                                                <div className="text-xs text-secondary">
                                                    Run queries live against this Postgres connection. Data from this
                                                    source can&apos;t be joined with PostHog data.
                                                </div>
                                            </div>
                                        ),
                                    },
                                ]}
                            />
                        )}
                    </LemonField>
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
