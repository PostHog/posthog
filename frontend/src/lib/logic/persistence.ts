import { getCurrentOrganizationIdOrNone, getCurrentTeamId, getCurrentUserIdOrNone } from 'lib/utils/getAppContext'

interface TeamScopedPersistenceConfig {
    persist: true
    prefix: string
}

interface TeamScopedStorageConfig {
    persist: true
    storageKey: string
}

interface UserScopedPersistenceConfig {
    persist: true
    prefix: string
}

const getTeamStoragePrefix = (): string => {
    return `${getCurrentTeamId()}__`
}

const getUserStoragePrefix = (): string => {
    return `${getCurrentUserIdOrNone() ?? 'anonymous'}__${getTeamStoragePrefix()}`
}

export const buildTeamScopedPersistenceConfig = (prefix: string = ''): TeamScopedPersistenceConfig => ({
    persist: true,
    prefix: `${getTeamStoragePrefix()}${prefix}`,
})

export const buildTeamScopedStorageConfig = (storageKey: string): TeamScopedStorageConfig => ({
    persist: true,
    storageKey: `${getTeamStoragePrefix()}${storageKey}`,
})

export const buildUserScopedPersistenceConfig = (prefix: string = ''): UserScopedPersistenceConfig => ({
    persist: true,
    prefix: `${getUserStoragePrefix()}${prefix}`,
})

/**
 * For state that belongs to the organization instead of to one project. The key carries the user ID
 * too, so one user of a shared browser profile never reads another user's value. This helper does
 * not throw when an ID is unknown, because logics that mount app-wide can run before the app knows
 * the current organization.
 */
export const buildUserScopedOrganizationPersistenceConfig = (prefix: string = ''): UserScopedPersistenceConfig => ({
    persist: true,
    prefix: `${getCurrentUserIdOrNone() ?? 'anonymous'}__${getCurrentOrganizationIdOrNone() ?? 'no-organization'}__${prefix}`,
})
