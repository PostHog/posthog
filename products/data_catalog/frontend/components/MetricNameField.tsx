import { useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { sqlNameFromDisplayName } from '../common'

export interface MetricNameValue {
    display_name: string
    name: string
}

export interface MetricNameFieldProps {
    displayName: string
    sqlName: string
    onChange: (value: MetricNameValue) => void
    displayNameError?: string
    sqlNameError?: string
    sqlNameTaken?: boolean
    autoFocus?: boolean
}

export function MetricNameField({
    displayName,
    sqlName,
    onChange,
    displayNameError,
    sqlNameError,
    sqlNameTaken,
    autoFocus,
}: MetricNameFieldProps): JSX.Element {
    const [editingSqlName, setEditingSqlName] = useState(false)
    const automaticSqlName = sqlNameFromDisplayName(displayName)
    const cannotDeriveSqlName = !!displayName.trim() && !automaticSqlName
    const showSqlNameInput = editingSqlName || !!sqlNameError || cannotDeriveSqlName

    const changeDisplayName = (nextDisplayName: string): void => {
        const followsDisplayName = sqlName === automaticSqlName
        onChange({
            display_name: nextDisplayName,
            name: followsDisplayName ? sqlNameFromDisplayName(nextDisplayName) : sqlName,
        })
    }

    const restoreAutomaticSqlName = (): void => {
        setEditingSqlName(false)
        onChange({ display_name: displayName, name: automaticSqlName })
    }

    return (
        <div className="flex flex-col gap-2">
            <LemonField.Pure label="Name" error={displayNameError}>
                <LemonInput
                    value={displayName}
                    onChange={changeDisplayName}
                    placeholder="Monthly active users"
                    autoFocus={autoFocus}
                    data-attr="data-catalog-metric-name-input"
                />
            </LemonField.Pure>
            {showSqlNameInput ? (
                <LemonField.Pure
                    label="SQL name"
                    error={sqlNameError}
                    help="Queries, the API, and agents use this name to find the metric."
                >
                    <LemonInput
                        value={sqlName}
                        onChange={(name) => onChange({ display_name: displayName, name })}
                        placeholder="monthly_active_users"
                        size="small"
                        data-attr="data-catalog-metric-sql-name-input"
                    />
                </LemonField.Pure>
            ) : sqlName ? (
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-secondary min-w-0">
                    <span>SQL name</span>
                    <code className="truncate max-w-full" title={sqlName}>
                        {sqlName}
                    </code>
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        onClick={() => setEditingSqlName(true)}
                        data-attr="data-catalog-metric-sql-name-edit"
                    >
                        Edit
                    </LemonButton>
                </div>
            ) : null}
            {(sqlNameTaken || (automaticSqlName && sqlName !== automaticSqlName)) && (
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
                    {sqlNameTaken && (
                        <span className="text-warning-dark">
                            <code>{sqlName}</code> is already used.{' '}
                            <Link to={urls.dataCatalogMetric(sqlName)} target="_blank">
                                Open it
                            </Link>
                        </span>
                    )}
                    {automaticSqlName && sqlName !== automaticSqlName && (
                        <Link onClick={restoreAutomaticSqlName} data-attr="data-catalog-metric-sql-name-reset">
                            Use "{automaticSqlName}"
                        </Link>
                    )}
                </div>
            )}
        </div>
    )
}
