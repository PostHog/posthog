import { getCurrentTeamId } from 'lib/utils/getAppContext'

interface TeamScopedPersistenceConfig {
    persist: true
    prefix: string
}

interface TeamScopedStorageConfig {
    persist: true
    storageKey: string
}

const getTeamStoragePrefix = (): string => {
    return `${getCurrentTeamId()}__`
}

export const buildTeamScopedPersistenceConfig = (prefix: string = ''): TeamScopedPersistenceConfig => ({
    persist: true,
    prefix: `${getTeamStoragePrefix()}${prefix}`,
})

export const buildTeamScopedStorageConfig = (storageKey: string): TeamScopedStorageConfig => ({
    persist: true,
    storageKey: `${getTeamStoragePrefix()}${storageKey}`,
})
