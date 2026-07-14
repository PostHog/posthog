import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import {
    dataWarehouseUsersCreate,
    dataWarehouseUsersDestroy,
    dataWarehouseUsersDisableCreate,
    dataWarehouseUsersEnableCreate,
    dataWarehouseUsersList,
    dataWarehouseUsersResetPasswordCreate,
} from 'products/data_warehouse/frontend/generated/api'
import type {
    ManagedWarehouseUserApi,
    ManagedWarehouseUserConnectionApi,
} from 'products/data_warehouse/frontend/generated/api.schemas'

import type { dbUsersLogicType } from './dbUsersLogicType'
import { warehouseProvisioningLogic } from './warehouseProvisioningLogic'

// Lowercase letters, numbers, and underscores; must start with a letter. Mirrors the backend
// validator in products/data_warehouse/backend/presentation/views/managed_warehouse_users.py.
const USERNAME_REGEX = /^[a-z][a-z0-9_]{2,62}$/

export interface DbUserCredentials {
    action: 'create' | 'reset'
    username: string
    password: string
    connection: ManagedWarehouseUserConnectionApi | null
}

const currentProjectId = (): string => String(teamLogic.values.currentTeamId)

function errorMessage(e: unknown, fallback: string): string {
    return e instanceof Error && e.message ? e.message : fallback
}

export const dbUsersLogic = kea<dbUsersLogicType>([
    path(['scenes', 'data-warehouse', 'scene', 'dbUsersLogic']),

    connect(() => ({
        values: [warehouseProvisioningLogic, ['warehouseStatus']],
    })),

    actions({
        openCreateModal: true,
        closeCreateModal: true,
        setNewUsername: (username: string) => ({ username }),
        createUser: (username: string) => ({ username }),
        createUserComplete: true,
        deleteUser: (username: string) => ({ username }),
        deleteUserComplete: (username: string) => ({ username }),
        resetPassword: (username: string) => ({ username }),
        resetPasswordComplete: (username: string) => ({ username }),
        disableUser: (username: string) => ({ username }),
        disableUserComplete: (username: string) => ({ username }),
        enableUser: (username: string) => ({ username }),
        enableUserComplete: (username: string) => ({ username }),
        setCredentials: (credentials: DbUserCredentials) => ({ credentials }),
        clearCredentials: true,
    }),

    loaders(() => ({
        dbUsers: [
            [] as ManagedWarehouseUserApi[],
            {
                loadDbUsers: async () => await dataWarehouseUsersList(currentProjectId()),
            },
        ],
    })),

    reducers({
        isCreateModalOpen: [
            false,
            {
                openCreateModal: () => true,
                closeCreateModal: () => false,
            },
        ],
        newUsername: [
            '',
            {
                setNewUsername: (_, { username }) => username,
                openCreateModal: () => '',
                closeCreateModal: () => '',
            },
        ],
        isCreatingUser: [
            false,
            {
                createUser: () => true,
                createUserComplete: () => false,
            },
        ],
        // Username of the row a mutation is currently in flight for, keyed per action so buttons on
        // other rows (and other actions on the same row) stay usable while one request is pending.
        deletingUsername: [
            null as string | null,
            {
                deleteUser: (_, { username }) => username,
                deleteUserComplete: () => null,
            },
        ],
        resettingUsername: [
            null as string | null,
            {
                resetPassword: (_, { username }) => username,
                resetPasswordComplete: () => null,
            },
        ],
        disablingUsername: [
            null as string | null,
            {
                disableUser: (_, { username }) => username,
                disableUserComplete: () => null,
            },
        ],
        enablingUsername: [
            null as string | null,
            {
                enableUser: (_, { username }) => username,
                enableUserComplete: () => null,
            },
        ],
        // Credentials from the most recent create/reset, shown exactly once in a modal. Cleared
        // when that modal closes so a stale password can't be reopened.
        credentials: [
            null as DbUserCredentials | null,
            {
                setCredentials: (_, { credentials }) => credentials,
                clearCredentials: () => null,
            },
        ],
    }),

    selectors({
        // The org's root database user is never mutable here — it's managed from warehouse
        // Settings instead. Falls back to the literal "root" so the tag still applies before
        // warehouseStatus has loaded, mirroring the backend's own protection check.
        rootUsername: [
            (s) => [s.warehouseStatus],
            (warehouseStatus): string => warehouseStatus?.connection?.username ?? 'root',
        ],
        isValidNewUsername: [(s) => [s.newUsername], (newUsername): boolean => USERNAME_REGEX.test(newUsername)],
    }),

    listeners(({ actions, values }) => ({
        createUser: async ({ username }) => {
            try {
                const result = await dataWarehouseUsersCreate(currentProjectId(), { username })
                actions.setCredentials({
                    action: 'create',
                    username: result.username,
                    password: result.password,
                    connection: result.connection,
                })
                actions.closeCreateModal()
                lemonToast.success(`Created database user "${username}"`)
                actions.loadDbUsers()
            } catch (e: unknown) {
                lemonToast.error(errorMessage(e, `Failed to create user "${username}"`))
            }
            actions.createUserComplete()
        },

        deleteUser: async ({ username }) => {
            try {
                await dataWarehouseUsersDestroy(currentProjectId(), username)
                lemonToast.success(`Deleted database user "${username}"`)
                actions.loadDbUsers()
            } catch (e: unknown) {
                lemonToast.error(errorMessage(e, `Failed to delete user "${username}"`))
            }
            actions.deleteUserComplete(username)
        },

        resetPassword: async ({ username }) => {
            try {
                const result = await dataWarehouseUsersResetPasswordCreate(currentProjectId(), username)
                // The reset-password response doesn't echo connection details (they don't change),
                // so borrow them from the warehouse's connection info, known good since this tab only
                // renders once the warehouse is ready.
                const warehouseConnection = values.warehouseStatus?.connection
                actions.setCredentials({
                    action: 'reset',
                    username: result.username,
                    password: result.password,
                    connection: warehouseConnection
                        ? {
                              host: warehouseConnection.host,
                              port: warehouseConnection.port,
                              database: warehouseConnection.database,
                              username: result.username,
                          }
                        : null,
                })
                lemonToast.success(`Password reset for "${username}"`)
                actions.loadDbUsers()
            } catch (e: unknown) {
                lemonToast.error(errorMessage(e, `Failed to reset password for "${username}"`))
            }
            actions.resetPasswordComplete(username)
        },

        disableUser: async ({ username }) => {
            try {
                const result = await dataWarehouseUsersDisableCreate(currentProjectId(), username)
                lemonToast.success(
                    result.killed > 0
                        ? `Disabled "${username}" and ended ${result.killed} active session${result.killed === 1 ? '' : 's'}`
                        : `Disabled "${username}"`
                )
                actions.loadDbUsers()
            } catch (e: unknown) {
                lemonToast.error(errorMessage(e, `Failed to disable "${username}"`))
            }
            actions.disableUserComplete(username)
        },

        enableUser: async ({ username }) => {
            try {
                await dataWarehouseUsersEnableCreate(currentProjectId(), username)
                lemonToast.success(`Enabled "${username}"`)
                actions.loadDbUsers()
            } catch (e: unknown) {
                lemonToast.error(errorMessage(e, `Failed to enable "${username}"`))
            }
            actions.enableUserComplete(username)
        },
    })),

    afterMount(({ actions }) => {
        actions.loadDbUsers()
    }),
])
