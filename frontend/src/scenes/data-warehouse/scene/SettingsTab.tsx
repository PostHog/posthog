import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCheck, IconEye, IconHide, IconX } from '@posthog/icons'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { DataWarehouseProvisioningConnection, DataWarehouseProvisioningState } from '~/types'

import { warehouseProvisioningLogic } from './warehouseProvisioningLogic'

function stateToTagType(state: DataWarehouseProvisioningState): 'success' | 'warning' | 'danger' | 'default' {
    switch (state) {
        case 'ready':
            return 'success'
        case 'pending':
        case 'provisioning':
        case 'deleting':
            return 'warning'
        case 'failed':
            return 'danger'
        case 'deleted':
        default:
            return 'default'
    }
}

function ConnectionDetails({ connection }: { connection: DataWarehouseProvisioningConnection }): JSX.Element {
    const { host, port, database, username, password } = connection
    const [showPassword, setShowPassword] = useState(false)
    const psqlCmd = `psql "host=${host} port=${port} dbname=${database} user=${username} sslmode=require"`

    return (
        <div className="border rounded p-4 space-y-3">
            <h3 className="mb-2">Connection details</h3>
            <div className="grid grid-cols-2 gap-3">
                <div>
                    <LemonLabel>Host</LemonLabel>
                    <CodeSnippet compact thing="host">
                        {host}
                    </CodeSnippet>
                </div>
                <div>
                    <LemonLabel>Port</LemonLabel>
                    <CodeSnippet compact thing="port">
                        {String(port)}
                    </CodeSnippet>
                </div>
                <div>
                    <LemonLabel>Database</LemonLabel>
                    <CodeSnippet compact thing="database">
                        {database}
                    </CodeSnippet>
                </div>
                <div>
                    <LemonLabel>Username</LemonLabel>
                    <CodeSnippet compact thing="username">
                        {username}
                    </CodeSnippet>
                </div>
            </div>
            <div>
                <LemonLabel>Password</LemonLabel>
                <CodeSnippet
                    compact
                    thing="password"
                    actions={
                        <LemonButton
                            size="small"
                            noPadding
                            icon={showPassword ? <IconHide /> : <IconEye />}
                            onClick={() => setShowPassword(!showPassword)}
                            tooltip={showPassword ? 'Hide password' : 'Show password'}
                        />
                    }
                >
                    {showPassword ? password : '••••••••••••••••••'}
                </CodeSnippet>
            </div>
            <div>
                <LemonLabel>Connect with psql</LemonLabel>
                <CodeSnippet compact thing="psql command">
                    {psqlCmd}
                </CodeSnippet>
            </div>
        </div>
    )
}

export function SettingsTab(): JSX.Element {
    const {
        warehouseStatus,
        warehouseStatusLoading,
        isProvisioning,
        isDeprovisioning,
        isInProgress,
        databaseName,
        databaseNameAvailable,
        databaseNameChecking,
        isValidDatabaseName,
        canProvision,
    } = useValues(warehouseProvisioningLogic)
    const { provisionWarehouse, deprovisionWarehouse, setDatabaseName } = useActions(warehouseProvisioningLogic)

    const hasWarehouse = warehouseStatus && warehouseStatus.state !== 'deleted'
    const isReady = warehouseStatus?.state === 'ready'
    const isFailed = warehouseStatus?.state === 'failed'

    return (
        <div className="mt-4 space-y-4 max-w-160">
            <div>
                <h2 className="mb-2">Managed Warehouse</h2>
                {!isReady && (
                    <p className="text-muted mb-4">
                        Provision a dedicated data warehouse with Aurora, S3, and isolated compute for your team.
                    </p>
                )}
            </div>

            {warehouseStatusLoading && !warehouseStatus ? (
                <div className="flex items-center gap-2">
                    <Spinner />
                    <span>Loading warehouse status...</span>
                </div>
            ) : !hasWarehouse ? (
                <div className="space-y-4">
                    <div>
                        <LemonLabel>Database name</LemonLabel>
                        <div className="flex items-center gap-2">
                            <LemonInput
                                value={databaseName}
                                onChange={setDatabaseName}
                                placeholder="my-warehouse"
                                fullWidth
                            />
                            {databaseName &&
                                isValidDatabaseName &&
                                (databaseNameChecking ? (
                                    <Spinner className="text-muted" />
                                ) : databaseNameAvailable === true ? (
                                    <IconCheck className="text-success text-xl" />
                                ) : (
                                    <IconX className="text-danger text-xl" />
                                ))}
                        </div>
                        {databaseName &&
                            isValidDatabaseName &&
                            !databaseNameChecking &&
                            databaseNameAvailable !== true && (
                                <p className="text-danger text-xs mt-1">
                                    {databaseNameAvailable === false
                                        ? 'This database name is already taken.'
                                        : 'Unable to verify database name availability.'}
                                </p>
                            )}
                        {databaseName && !isValidDatabaseName && (
                            <p className="text-danger text-xs mt-1">
                                Must be 3-63 characters, start with a lowercase letter, and contain only lowercase
                                letters, numbers, hyphens, or underscores.
                            </p>
                        )}
                        {(!databaseName ||
                            (isValidDatabaseName && (databaseNameChecking || databaseNameAvailable === true))) && (
                            <p className="text-muted text-xs mt-1">
                                Unique name for your database. This is what you'll use in <code>dbname=</code> when
                                connecting.
                            </p>
                        )}
                    </div>
                    <LemonButton
                        type="primary"
                        loading={isProvisioning}
                        disabledReason={!canProvision ? 'Enter an available database name' : undefined}
                        onClick={() => {
                            LemonDialog.open({
                                title: 'Provision managed warehouse?',
                                description:
                                    'This will create dedicated AWS resources (Aurora database, S3 bucket, IAM roles) for your team. This typically takes 5-15 minutes.',
                                primaryButton: {
                                    children: 'Provision',
                                    onClick: () => provisionWarehouse({ databaseName }),
                                },
                                secondaryButton: {
                                    children: 'Cancel',
                                },
                            })
                        }}
                        data-attr="provision-warehouse"
                    >
                        Provision warehouse
                    </LemonButton>
                </div>
            ) : (
                <div className="space-y-4">
                    {isFailed && (
                        <LemonBanner type="error">
                            Provisioning failed: {warehouseStatus?.status_message || 'Unknown error'}
                        </LemonBanner>
                    )}

                    {isInProgress && (
                        <LemonBanner type="info">
                            <div className="flex items-center gap-2">
                                <Spinner />
                                <span>
                                    {warehouseStatus?.state === 'deleting'
                                        ? 'Deprovisioning in progress...'
                                        : 'Provisioning in progress...'}
                                </span>
                            </div>
                        </LemonBanner>
                    )}

                    <div className="border rounded px-4 pt-4 pb-3 space-y-2">
                        <div className="flex items-center justify-between">
                            <h3 className="mb-0">Status</h3>
                            <LemonTag type={stateToTagType(warehouseStatus!.state)}>
                                {warehouseStatus!.state.toUpperCase()}
                            </LemonTag>
                        </div>

                        {warehouseStatus!.ready_at && (
                            <p className="text-muted text-xs">
                                Ready since: {new Date(warehouseStatus!.ready_at).toLocaleString()}
                            </p>
                        )}
                    </div>

                    {isReady && warehouseStatus?.connection && (
                        <ConnectionDetails connection={warehouseStatus.connection} />
                    )}

                    <div className="flex gap-2">
                        {isFailed && (
                            <LemonButton
                                type="primary"
                                loading={isProvisioning}
                                onClick={() => provisionWarehouse({ databaseName })}
                                data-attr="retry-provision-warehouse"
                            >
                                Retry provisioning
                            </LemonButton>
                        )}
                        {(isReady || isFailed) && (
                            <LemonButton
                                type="secondary"
                                status="danger"
                                loading={isDeprovisioning}
                                onClick={() => {
                                    LemonDialog.open({
                                        title: 'Deprovision managed warehouse?',
                                        description:
                                            'This will delete all AWS resources (Aurora database, S3 bucket, IAM roles) for your team. This action cannot be undone.',
                                        primaryButton: {
                                            children: 'Deprovision',
                                            status: 'danger',
                                            onClick: () => deprovisionWarehouse(),
                                        },
                                        secondaryButton: {
                                            children: 'Cancel',
                                        },
                                    })
                                }}
                                data-attr="deprovision-warehouse"
                            >
                                Deprovision warehouse
                            </LemonButton>
                        )}
                    </div>
                </div>
            )}
        </div>
    )
}
