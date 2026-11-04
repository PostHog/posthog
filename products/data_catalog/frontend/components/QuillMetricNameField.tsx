import { useId, useState } from 'react'

import { Button, Field, FieldDescription, FieldError, FieldLabel, Input, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { sqlNameAfterDisplayNameChange, sqlNameFromDisplayName } from '../common'
import type { MetricNameFieldProps } from './MetricNameField'

export function QuillMetricNameField({
    displayName,
    sqlName,
    onChange,
    displayNameError,
    sqlNameError,
    sqlNameTaken,
    autoFocus,
}: MetricNameFieldProps): JSX.Element {
    const [editingSqlName, setEditingSqlName] = useState(false)
    const nameId = useId()
    const sqlNameId = useId()
    const automaticSqlName = sqlNameFromDisplayName(displayName)
    const cannotDeriveSqlName = !!displayName.trim() && !automaticSqlName
    const showSqlNameInput = editingSqlName || !!sqlNameError || cannotDeriveSqlName
    const sqlNameDiffers = !!automaticSqlName && sqlName !== automaticSqlName

    const changeDisplayName = (nextDisplayName: string): void => {
        onChange({
            display_name: nextDisplayName,
            name: sqlNameAfterDisplayNameChange(displayName, sqlName, nextDisplayName),
        })
    }

    const restoreAutomaticSqlName = (): void => {
        setEditingSqlName(false)
        onChange({ display_name: displayName, name: automaticSqlName })
    }

    return (
        <div className="flex flex-col gap-2">
            <Field data-invalid={displayNameError ? true : undefined}>
                <FieldLabel htmlFor={nameId}>Name</FieldLabel>
                <Input
                    id={nameId}
                    value={displayName}
                    onChange={(event) => changeDisplayName(event.target.value)}
                    placeholder="Monthly active users"
                    autoFocus={autoFocus}
                    aria-invalid={displayNameError ? true : undefined}
                    data-attr="data-catalog-metric-name-input"
                />
                {displayNameError && <FieldError>{displayNameError}</FieldError>}
            </Field>
            {showSqlNameInput ? (
                <Field data-invalid={sqlNameError ? true : undefined}>
                    <FieldLabel htmlFor={sqlNameId}>SQL name</FieldLabel>
                    <Input
                        id={sqlNameId}
                        size="sm"
                        value={sqlName}
                        onChange={(event) => onChange({ display_name: displayName, name: event.target.value })}
                        placeholder="monthly_active_users"
                        aria-invalid={sqlNameError ? true : undefined}
                        data-attr="data-catalog-metric-sql-name-input"
                    />
                    <FieldDescription>Queries, the API, and agents use this name to find the metric.</FieldDescription>
                    {sqlNameError && <FieldError>{sqlNameError}</FieldError>}
                </Field>
            ) : sqlName ? (
                <Text
                    size="xs"
                    variant="muted"
                    render={<div className="m-0 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1" />}
                >
                    <span>SQL name</span>
                    <code className="max-w-full truncate" title={sqlName}>
                        {sqlName}
                    </code>
                    <Button
                        variant="link"
                        size="inline"
                        onClick={() => setEditingSqlName(true)}
                        data-attr="data-catalog-metric-sql-name-edit"
                    >
                        Edit
                    </Button>
                </Text>
            ) : null}
            {(sqlNameTaken || sqlNameDiffers) && (
                <Text size="xs" render={<div className="m-0 flex flex-wrap items-center gap-x-2 gap-y-1" />}>
                    {sqlNameTaken && (
                        <span className="text-warning-foreground">
                            <code>{sqlName}</code> is already used.{' '}
                            <Button
                                variant="link"
                                size="inline"
                                render={<LinkPrimitive to={urls.dataCatalogMetric(sqlName)} target="_blank" />}
                            >
                                Open it
                            </Button>
                        </span>
                    )}
                    {sqlNameDiffers && (
                        <Button
                            variant="link"
                            size="inline"
                            onClick={restoreAutomaticSqlName}
                            data-attr="data-catalog-metric-sql-name-reset"
                        >
                            Use "{automaticSqlName}"
                        </Button>
                    )}
                </Text>
            )}
        </div>
    )
}
