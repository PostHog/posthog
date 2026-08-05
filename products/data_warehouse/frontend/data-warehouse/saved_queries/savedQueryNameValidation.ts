// Must stay in sync with validate_saved_query_name in
// products/data_warehouse/backend/models/datawarehouse_saved_query.py — the `.`
// is load-bearing and drives HogQL namespace nesting (see
// posthog/hogql/database/database.py splitting saved query names on `.`).
export const SAVED_QUERY_NAME_REGEX = /^[A-Za-z_$][A-Za-z0-9_.$]*$/

export const validateSavedQueryName = (name: string | undefined | null): string | undefined => {
    if (!name) {
        return 'You must enter a name'
    }
    if (!SAVED_QUERY_NAME_REGEX.test(name)) {
        return "View names must start with a letter, '_', or '$' and can only contain letters, numbers, '_', '.', or '$'"
    }
    return undefined
}
