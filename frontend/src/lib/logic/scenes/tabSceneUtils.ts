import { router } from 'kea-router'

export function getTabSceneParams(tabId: string): {
    searchParams: Record<string, any>
    hashParams: Record<string, any>
} {
    void tabId
    return {
        searchParams: router.values.searchParams,
        hashParams: router.values.hashParams,
    }
}

export function updateTabUrl(
    tabId: string,
    pathname: string,
    searchParams: Record<string, any>,
    hashParams: Record<string, any>
): void {
    void tabId
    router.actions.replace(pathname, searchParams, hashParams)
}
