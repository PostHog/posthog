export function sortScopesWriteFirst(scopes: string[]): string[] {
    return [...scopes].sort((a, b) => {
        const aIsWrite = a.endsWith(':write')
        const bIsWrite = b.endsWith(':write')
        if (aIsWrite && !bIsWrite) {
            return -1
        }
        if (!aIsWrite && bIsWrite) {
            return 1
        }
        return 0
    })
}
