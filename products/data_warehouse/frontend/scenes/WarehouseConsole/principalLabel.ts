const KIND_LABELS: Record<string, string> = {
    materialization: 'Materialized views',
    'sql-editor': 'SQL editor',
    endpoints: 'Endpoints',
}

const PRINCIPAL_PATTERN = /^posthog:([a-z0-9_-]+):team:(\d+)(?::user:(\d+))?$/i

export interface PrincipalLabelContext {
    /** Project names by id, from the organization's projects. */
    teamNames: Record<number, string>
    currentUserId: number | null | undefined
}

/**
 * One label for a Trino login everywhere. The server's `principal_label` wins. A raw principal such as
 * `posthog:materialization:team:1` becomes "Materialized views · Hedgebox". Other logins stay as they are.
 */
export function principalLabel(principal: string, context: PrincipalLabelContext, serverLabel?: string | null): string {
    if (serverLabel) {
        return serverLabel
    }
    if (!principal) {
        return 'Unknown'
    }
    const match = PRINCIPAL_PATTERN.exec(principal)
    if (!match) {
        return principal
    }
    const [, kind, teamId, userId] = match
    const kindLabel =
        KIND_LABELS[kind.toLowerCase()] ?? kind.charAt(0).toUpperCase() + kind.slice(1).replaceAll(/[-_]/g, ' ')
    if (userId && context.currentUserId != null && Number(userId) === context.currentUserId) {
        return `${kindLabel} · You`
    }
    return `${kindLabel} · ${context.teamNames[Number(teamId)] ?? `Project ${teamId}`}`
}
