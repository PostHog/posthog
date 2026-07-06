import { useActions, useValues } from 'kea'

import { IconCheck, IconX } from '@posthog/icons'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Spinner } from 'lib/lemon-ui/Spinner'

import type {
    WarehouseConnectionApi,
    WarehouseStatusResponseStateEnumApi,
} from 'products/data_warehouse/frontend/generated/api.schemas'

import { warehouseProvisioningLogic } from './warehouseProvisioningLogic'

function stateToTagType(state: WarehouseStatusResponseStateEnumApi): 'success' | 'warning' | 'danger' | 'default' {
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

function ConnectionDetails({ connection }: { connection: WarehouseConnectionApi }): JSX.Element {
    const { host, port, database, username } = connection
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
                <LemonLabel>Connect with psql</LemonLabel>
                <CodeSnippet compact wrap thing="psql command">
                    {psqlCmd}
                </CodeSnippet>
            </div>
            <p className="text-muted text-xs mb-0">
                The password is shown only once, when you provision the warehouse. If you didn't save it, use "Reset
                password" below to generate a new one.
            </p>
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
        canRetryProvision,
        retryDatabaseName,
        initialPassword,
        isResettingPassword,
        warehouseDomain,
        tableName,
        isValidTableName,
        isEnablingBackfill,
        backfillTableSuffix,
        hasBackfill,
    } = useValues(warehouseProvisioningLogic)
    const {
        provisionWarehouse,
        deprovisionWarehouse,
        setDatabaseName,
        clearInitialPassword,
        resetPassword,
        setTableName,
        enableBackfill,
    } = useActions(warehouseProvisioningLogic)
    const deprovisionRestrictionReason = useRestrictedArea({
        scope: RestrictionScope.Organization,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    const hasWarehouse = warehouseStatus && warehouseStatus.state !== 'deleted'
    const isReady = warehouseStatus?.state === 'ready'
    const isFailed = warehouseStatus?.state === 'failed'
    const showProvisionForm = !hasWarehouse || isFailed

    return (
        <div className="mt-4 space-y-4 max-w-160">
            <div>
                <h2 className="mb-2">Managed warehouse</h2>
                {!isReady && (
                    <p className="text-muted mb-4">This warehouse is shared by every project in the organization.</p>
                )}
            </div>

            {initialPassword && (
                <LemonBanner type="warning" onClose={clearInitialPassword}>
                    <div className="space-y-2">
                        <strong>Save your password now — it won't be shown again.</strong>
                        <CodeSnippet compact thing="password">
                            {initialPassword}
                        </CodeSnippet>
                    </div>
                </LemonBanner>
            )}

            {warehouseStatusLoading && !warehouseStatus ? (
                <div className="flex items-center gap-2">
                    <Spinner />
                    <span>Loading warehouse status...</span>
                </div>
            ) : showProvisionForm ? (
                <div className="space-y-4">
                    {isFailed && (
                        <LemonBanner type="error">
                            Provisioning failed: {warehouseStatus?.status_message || 'Unknown error'}
                        </LemonBanner>
                    )}
                    <div>
                        <LemonLabel>Warehouse name</LemonLabel>
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
                                    {isFailed
                                        ? 'Availability checks are advisory during retry provisioning.'
                                        : databaseNameAvailable === false
                                          ? 'This database name is already taken.'
                                          : 'Unable to verify database name availability.'}
                                </p>
                            )}
                        {databaseName && !isValidDatabaseName && (
                            <p className="text-danger text-xs mt-1">
                                Must be 3-63 characters: lowercase letters, numbers, and hyphens, starting with a letter
                                and ending with a letter or number.
                            </p>
                        )}
                        {databaseName &&
                        isValidDatabaseName &&
                        !databaseNameChecking &&
                        databaseNameAvailable === true &&
                        warehouseDomain ? (
                            <p className="text-muted text-xs mt-1">
                                Your warehouse will be available at{' '}
                                <code>
                                    {databaseName}.dw.{warehouseDomain}
                                </code>
                                . You always connect with <code>dbname=ducklake</code>.
                            </p>
                        ) : !databaseName ||
                          (isValidDatabaseName && (databaseNameChecking || databaseNameAvailable === true)) ? (
                            <p className="text-muted text-xs mt-1">
                                Unique name for your warehouse. It becomes the subdomain of your connection host (e.g.{' '}
                                <code>my-warehouse.dw.{warehouseDomain ?? 'us.postwh.com'}</code>). You always connect
                                with <code>dbname=ducklake</code>.
                            </p>
                        ) : null}
                    </div>
                    <div>
                        <LemonLabel>Table name</LemonLabel>
                        <LemonInput value={tableName} onChange={setTableName} placeholder="my_project" fullWidth />
                        {tableName && !isValidTableName ? (
                            <p className="text-danger text-xs mt-1">
                                Use lowercase letters, numbers, and underscores only (max 63 characters).
                            </p>
                        ) : (
                            <p className="text-muted text-xs mt-1">
                                This project's data lands in its own warehouse tables, suffixed with this name (e.g.{' '}
                                <code>events_&lt;name&gt;</code>, <code>persons_&lt;name&gt;</code>). Other projects
                                pick their own when they join.
                            </p>
                        )}
                    </div>
                    <LemonButton
                        type="primary"
                        loading={isProvisioning}
                        disabledReason={
                            isFailed
                                ? !canRetryProvision
                                    ? 'Enter a valid database name and table name'
                                    : undefined
                                : !canProvision
                                  ? 'Enter an available database name and table name'
                                  : undefined
                        }
                        onClick={() => {
                            LemonDialog.open({
                                title: isFailed
                                    ? 'Retry managed warehouse provisioning?'
                                    : 'Provision managed warehouse?',
                                description:
                                    'This will create a managed warehouse for your organization, shared by every project in it. Should take less than 5 minutes.',
                                primaryButton: {
                                    children: isFailed ? 'Retry provisioning' : 'Provision',
                                    onClick: () => provisionWarehouse({ databaseName: retryDatabaseName, tableName }),
                                },
                                secondaryButton: {
                                    children: 'Cancel',
                                },
                            })
                        }}
                        data-attr={isFailed ? 'retry-provision-warehouse' : 'provision-warehouse'}
                    >
                        {isFailed ? 'Retry provisioning' : 'Provision warehouse'}
                    </LemonButton>
                </div>
            ) : (
                <div className="space-y-4">
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

                    {isReady && (
                        <div className="border rounded p-4 space-y-3">
                            <h3 className="mb-0">Warehouse tables for this project</h3>
                            {hasBackfill ? (
                                // A backfill already exists — the table name is fixed (immutable), so show
                                // read-only state rather than re-offering the form.
                                backfillTableSuffix ? (
                                    <p className="text-muted text-xs mb-0">
                                        This project writes to its own tables <code>events_{backfillTableSuffix}</code>{' '}
                                        / <code>persons_{backfillTableSuffix}</code>. The table name is fixed once a
                                        backfill is running.
                                    </p>
                                ) : (
                                    <p className="text-muted text-xs mb-0">
                                        This project writes to the shared <code>events</code> / <code>persons</code>{' '}
                                        tables. Changing it would split existing data, so it's fixed.
                                    </p>
                                )
                            ) : (
                                <>
                                    <p className="text-muted text-xs mb-0">
                                        Each project writes its data into its own tables in the shared warehouse so they
                                        don't merge. Choose a name for this project's warehouse tables — lowercase
                                        letters, numbers, and underscores only; it's used as the suffix (e.g.{' '}
                                        <code>events_&lt;name&gt;</code>). This can't be changed once a backfill runs.
                                    </p>
                                    <div>
                                        <div className="flex items-end gap-2">
                                            <div className="flex-1">
                                                <LemonLabel>Table name</LemonLabel>
                                                <LemonInput
                                                    value={tableName}
                                                    onChange={setTableName}
                                                    placeholder="my_project"
                                                    fullWidth
                                                />
                                            </div>
                                            <LemonButton
                                                type="primary"
                                                loading={isEnablingBackfill}
                                                disabledReason={
                                                    !isValidTableName ? 'Enter a valid table name' : undefined
                                                }
                                                onClick={() => enableBackfill({ tableName })}
                                                data-attr="enable-warehouse-backfill"
                                            >
                                                Enable backfill
                                            </LemonButton>
                                        </div>
                                        {tableName && !isValidTableName && (
                                            <p className="text-danger text-xs mt-1">
                                                Use lowercase letters, numbers, and underscores only (max 63
                                                characters).
                                            </p>
                                        )}
                                    </div>
                                </>
                            )}
                        </div>
                    )}

                    <div className="flex gap-2">
                        {isReady && (
                            <LemonButton
                                type="secondary"
                                loading={isResettingPassword}
                                onClick={() => {
                                    LemonDialog.open({
                                        title: 'Reset root password?',
                                        description:
                                            'This will generate a new password and invalidate the current one. Make sure to save the new password.',
                                        primaryButton: {
                                            children: 'Reset password',
                                            onClick: () => resetPassword(),
                                        },
                                        secondaryButton: {
                                            children: 'Cancel',
                                        },
                                    })
                                }}
                                data-attr="reset-warehouse-password"
                            >
                                Reset password
                            </LemonButton>
                        )}
                        {isReady && (
                            <LemonButton
                                type="secondary"
                                status="danger"
                                loading={isDeprovisioning}
                                disabledReason={deprovisionRestrictionReason ?? undefined}
                                onClick={() => {
                                    LemonDialog.open({
                                        title: 'Deprovision managed warehouse?',
                                        description:
                                            'This will delete the managed warehouse for your organization and every project in it. This action cannot be undone.',
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
