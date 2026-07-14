import { useActions, useValues } from 'kea'

import { IconLock, IconPlus, IconRefresh, IconTrash, IconUnlock } from '@posthog/icons'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTag } from 'lib/lemon-ui/LemonTag'

import type {
    ManagedWarehouseUserApi,
    ManagedWarehouseUserConnectionApi,
} from 'products/data_warehouse/frontend/generated/api.schemas'

import { DbUserCredentials, dbUsersLogic } from './dbUsersLogic'

function CredentialsDetails({
    username,
    password,
    connection,
}: {
    username: string
    password: string
    connection: ManagedWarehouseUserConnectionApi | null
}): JSX.Element {
    return (
        <div className="space-y-3">
            <div>
                <LemonLabel>Username</LemonLabel>
                <CodeSnippet compact thing="username">
                    {username}
                </CodeSnippet>
            </div>
            <div>
                <LemonLabel>Password</LemonLabel>
                <CodeSnippet compact thing="password">
                    {password}
                </CodeSnippet>
            </div>
            {connection && (
                <>
                    <div className="grid grid-cols-2 gap-3">
                        <div>
                            <LemonLabel>Host</LemonLabel>
                            <CodeSnippet compact thing="host">
                                {connection.host}
                            </CodeSnippet>
                        </div>
                        <div>
                            <LemonLabel>Port</LemonLabel>
                            <CodeSnippet compact thing="port">
                                {String(connection.port)}
                            </CodeSnippet>
                        </div>
                        <div>
                            <LemonLabel>Database</LemonLabel>
                            <CodeSnippet compact thing="database">
                                {connection.database}
                            </CodeSnippet>
                        </div>
                    </div>
                    <div>
                        <LemonLabel>Connect with psql</LemonLabel>
                        <CodeSnippet compact wrap thing="psql command">
                            {`psql "host=${connection.host} port=${connection.port} dbname=${connection.database} user=${username} sslmode=require"`}
                        </CodeSnippet>
                    </div>
                </>
            )}
            <p className="text-muted text-xs mb-0">
                This password won't be shown again. Save it now, or use "Reset password" later to generate a new one.
            </p>
        </div>
    )
}

function CredentialsModal({ credentials }: { credentials: DbUserCredentials }): JSX.Element {
    const { clearCredentials } = useActions(dbUsersLogic)

    return (
        <LemonModal
            isOpen
            onClose={clearCredentials}
            title={credentials.action === 'create' ? 'Database user created' : 'Password reset'}
            hasUnsavedInput
            footer={
                <LemonButton type="primary" onClick={clearCredentials}>
                    Done
                </LemonButton>
            }
        >
            <CredentialsDetails
                username={credentials.username}
                password={credentials.password}
                connection={credentials.connection}
            />
        </LemonModal>
    )
}

function CreateUserModal(): JSX.Element {
    const { isCreateModalOpen, newUsername, isValidNewUsername, isCreatingUser } = useValues(dbUsersLogic)
    const { closeCreateModal, setNewUsername, createUser } = useActions(dbUsersLogic)

    const handleSubmit = (): void => {
        if (isValidNewUsername) {
            createUser(newUsername)
        }
    }

    return (
        <LemonModal
            isOpen={isCreateModalOpen}
            onClose={closeCreateModal}
            title="New database user"
            footer={
                <LemonButton
                    type="primary"
                    loading={isCreatingUser}
                    disabledReason={!isValidNewUsername ? 'Enter a valid username' : undefined}
                    onClick={handleSubmit}
                >
                    Create user
                </LemonButton>
            }
        >
            <LemonLabel>Username</LemonLabel>
            <LemonInput
                value={newUsername}
                onChange={setNewUsername}
                placeholder="my_user"
                autoFocus
                fullWidth
                onPressEnter={handleSubmit}
            />
            <p className="text-muted text-xs mt-1 mb-0">
                Lowercase letters, numbers, and underscores only, starting with a letter. 3-63 characters.
            </p>
        </LemonModal>
    )
}

export function DbUsersTab(): JSX.Element {
    const {
        dbUsers,
        dbUsersLoading,
        rootUsername,
        deletingUsername,
        resettingUsername,
        disablingUsername,
        enablingUsername,
        credentials,
    } = useValues(dbUsersLogic)
    const { openCreateModal, deleteUser, resetPassword, disableUser, enableUser } = useActions(dbUsersLogic)

    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Organization,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    const columns: LemonTableColumns<ManagedWarehouseUserApi> = [
        {
            title: 'Username',
            key: 'username',
            render: (_, user) => (
                <div className="flex items-center gap-2">
                    <span className="font-medium">{user.username}</span>
                    {user.username === rootUsername && <LemonTag type="primary">Root</LemonTag>}
                </div>
            ),
            sorter: (a, b) => a.username.localeCompare(b.username),
        },
        {
            title: 'Status',
            key: 'disabled',
            render: (_, user) =>
                user.disabled ? (
                    <LemonTag type="danger">Disabled</LemonTag>
                ) : (
                    <LemonTag type="success">Active</LemonTag>
                ),
            sorter: (a, b) => Number(a.disabled) - Number(b.disabled),
        },
        createdAtColumn() as LemonTableColumn<ManagedWarehouseUserApi, keyof ManagedWarehouseUserApi | undefined>,
        {
            title: '',
            key: 'actions',
            render: (_, user) => {
                if (user.username === rootUsername) {
                    return null
                }
                const isDeleting = deletingUsername === user.username
                const isResetting = resettingUsername === user.username
                const isDisabling = disablingUsername === user.username
                const isEnabling = enablingUsername === user.username
                const busy = isDeleting || isResetting || isDisabling || isEnabling
                const busyElsewhereReason = (thisAction: boolean): string | undefined =>
                    busy && !thisAction ? 'Another action is in progress' : undefined

                return (
                    <div className="flex items-center gap-1 justify-end">
                        <LemonButton
                            tooltip="Reset password"
                            icon={<IconRefresh />}
                            size="small"
                            loading={isResetting}
                            disabledReason={restrictionReason ?? busyElsewhereReason(isResetting)}
                            onClick={() =>
                                LemonDialog.open({
                                    title: `Reset password for "${user.username}"?`,
                                    description:
                                        "The current password stops working immediately. Make sure you're ready to share the new one.",
                                    primaryButton: {
                                        children: 'Reset password',
                                        onClick: () => resetPassword(user.username),
                                    },
                                    secondaryButton: { children: 'Cancel' },
                                })
                            }
                        />
                        {user.disabled ? (
                            <LemonButton
                                tooltip="Enable"
                                icon={<IconUnlock />}
                                size="small"
                                loading={isEnabling}
                                disabledReason={restrictionReason ?? busyElsewhereReason(isEnabling)}
                                onClick={() => enableUser(user.username)}
                            />
                        ) : (
                            <LemonButton
                                tooltip="Disable"
                                icon={<IconLock />}
                                size="small"
                                loading={isDisabling}
                                disabledReason={restrictionReason ?? busyElsewhereReason(isDisabling)}
                                onClick={() =>
                                    LemonDialog.open({
                                        title: `Disable "${user.username}"?`,
                                        description:
                                            'This blocks new connections and immediately ends any of their live sessions.',
                                        primaryButton: {
                                            children: 'Disable user',
                                            status: 'danger',
                                            onClick: () => disableUser(user.username),
                                        },
                                        secondaryButton: { children: 'Cancel' },
                                    })
                                }
                            />
                        )}
                        <LemonButton
                            tooltip="Delete"
                            icon={<IconTrash />}
                            size="small"
                            status="danger"
                            loading={isDeleting}
                            disabledReason={restrictionReason ?? busyElsewhereReason(isDeleting)}
                            onClick={() =>
                                LemonDialog.open({
                                    title: `Delete "${user.username}"?`,
                                    description:
                                        "They will immediately lose access to the managed warehouse. This can't be undone.",
                                    primaryButton: {
                                        children: 'Delete user',
                                        status: 'danger',
                                        onClick: () => deleteUser(user.username),
                                    },
                                    secondaryButton: { children: 'Cancel' },
                                })
                            }
                        />
                    </div>
                )
            },
        },
    ]

    return (
        <div className="mt-4 space-y-4">
            <div className="flex items-center justify-between gap-3">
                <div>
                    <h2 className="mb-1">Database users</h2>
                    <p className="text-muted mb-0">
                        Manage the database users who can connect to your managed warehouse.
                    </p>
                </div>
                <LemonButton
                    type="primary"
                    icon={<IconPlus />}
                    disabledReason={restrictionReason ?? undefined}
                    onClick={openCreateModal}
                >
                    New user
                </LemonButton>
            </div>

            <LemonTable
                columns={columns}
                dataSource={dbUsers}
                loading={dbUsersLoading}
                rowKey="username"
                emptyState={
                    <div className="text-center">
                        <p className="mb-1">No database users yet.</p>
                        <p className="text-muted mb-0">Click "New user" above to create the first one.</p>
                    </div>
                }
            />

            <CreateUserModal />
            {credentials && <CredentialsModal credentials={credentials} />}
        </div>
    )
}
