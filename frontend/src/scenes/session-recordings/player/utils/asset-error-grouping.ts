export interface ResourceErrorDetails {
    resourceType: string
    resourceUrl: string
    message: string
    error?: any
}

export interface AssetErrorTypeGroup {
    count: number
    cspDirectives?: Record<string, number>
    urls?: Set<string>
}

export interface GroupedAssetErrors {
    total: number
    byType: Record<string, AssetErrorTypeGroup>
}

export interface DoctorDiagnostics {
    assetErrors: Record<string, Record<string, number> | string>
    assetErrorTotal: number
    assetErrorTypeNames: string
    rrwebWarningCount: number
    rrwebWarningSummary: Record<string, number>
}

export function emptyGroupedAssetErrors(): GroupedAssetErrors {
    return { total: 0, byType: {} }
}

export function addAssetError(group: GroupedAssetErrors, error: ResourceErrorDetails): void {
    group.total += 1

    const typeKey = error.resourceType
    if (!group.byType[typeKey]) {
        group.byType[typeKey] = { count: 0 }
        if (typeKey === 'csp') {
            group.byType[typeKey].cspDirectives = {}
        } else {
            group.byType[typeKey].urls = new Set()
        }
    }

    const typeGroup = group.byType[typeKey]
    typeGroup.count += 1

    if (typeKey === 'csp' && typeGroup.cspDirectives) {
        const CSP_PREFIX = 'CSP violation: '
        const directive = error.message.startsWith(CSP_PREFIX)
            ? error.message.slice(CSP_PREFIX.length).trim() || 'unknown'
            : error.message || 'unknown'
        typeGroup.cspDirectives[directive] = (typeGroup.cspDirectives[directive] || 0) + 1
    } else if (typeGroup.urls) {
        typeGroup.urls.add(error.resourceUrl)
    }
}

export function formatGroupedAssetErrors(group: GroupedAssetErrors): Record<string, Record<string, number> | string> {
    const result: Record<string, Record<string, number> | string> = {}
    for (const [type, typeGroup] of Object.entries(group.byType)) {
        const label = type === 'csp' ? `CSP violations (${typeGroup.count})` : `${type} errors (${typeGroup.count})`

        if (typeGroup.cspDirectives) {
            result[label] = { ...typeGroup.cspDirectives }
        } else if (typeGroup.urls) {
            const urls = [...typeGroup.urls].sort()
            result[label] =
                urls.length <= 3 ? urls.join(', ') : `${urls.slice(0, 3).join(', ')} + ${urls.length - 3} more`
        }
    }
    return result
}
