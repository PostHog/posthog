// Must stay in sync with validate_saved_query_name in
// products/data_modeling/backend/models/datawarehouse_saved_query.py — the `.`
// is load-bearing and drives HogQL namespace nesting (see
// posthog/hogql/database/database.py splitting saved query names on `.`).
export const SAVED_QUERY_NAME_REGEX = /^[A-Za-z_$][A-Za-z0-9_.$]*$/

export const validateSavedQueryName = (name: string | undefined | null): string | undefined => {
    if (!name) {
        return 'You must enter a name'
    }
    if (name === 'models') {
        return 'The models namespace needs a model name, for example models.revenue.'
    }
    if (!SAVED_QUERY_NAME_REGEX.test(name)) {
        return "View names must start with a letter, '_', or '$' and can only contain letters, numbers, '_', '.', or '$'"
    }
    return undefined
}

export const validateFolderName = (
    name: string | undefined | null,
    existingFolders: { name: string }[]
): string | undefined => {
    const trimmedName = name?.trim()
    if (!trimmedName) {
        return 'You must enter a folder name'
    }
    if (existingFolders.some((folder) => folder.name === trimmedName)) {
        return 'A folder with this name already exists'
    }
    return undefined
}
