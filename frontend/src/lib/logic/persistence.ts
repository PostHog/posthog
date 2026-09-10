import { getCurrentTeamId, getCurrentUserIdOrNone } from 'lib/utils/getAppContext'

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
