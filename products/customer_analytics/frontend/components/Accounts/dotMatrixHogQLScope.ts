export interface MatrixHogQLScope {
    usesFilters: boolean
    usesAccountId: boolean
    usesAccountExternalId: boolean
    usesAccountIds: boolean
    usesAccountExternalIds: boolean
}

const QUOTED_OR_COMMENT = /'(?:\\.|''|[^'\\])*'|"(?:\\.|""|[^"\\])*"|`(?:\\.|``|[^`\\])*`|--[^\n]*|\/\*[\s\S]*?\*\//g

// These are lexical hints. SQL still controls whether a placeholder restricts the returned rows.
export function getMatrixHogQLScope(query: string): MatrixHogQLScope {
    const sql = query.replace(QUOTED_OR_COMMENT, ' ')
    return {
        usesFilters: /\{\s*filters\s*(?:\}|\()/.test(sql),
        usesAccountId: /\{\s*account_id\s*\}/.test(sql),
        usesAccountExternalId: /\{\s*account_external_id\s*\}/.test(sql),
        usesAccountIds: /\{\s*account_ids\s*\}/.test(sql),
        usesAccountExternalIds: /\{\s*account_external_ids\s*\}/.test(sql),
    }
}

export function getMatrixHogQLScopeWarning(query: string): string | null {
    if (!query.trim() || Object.values(getMatrixHogQLScope(query)).some(Boolean)) {
        return null
    }
    return 'This query can include other accounts. Add an account condition to your WHERE clause: {filters} for events, or compare your account column with {account_external_id}.'
}
