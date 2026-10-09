import type { CloudAgentRepositoryApi } from '../generated/api.schemas'

export const IDLE_MINUTES_MIN = 1
export const IDLE_MINUTES_MAX = 120
export const IDLE_MINUTES_DEFAULT = 10

const REPOSITORY_PATTERN = /^[\w.-]+\/[\w.-]+$/

/** The form shows one repository for now, which is what the API accepts. */
export function repositoryFields(repositories: CloudAgentRepositoryApi[] | null | undefined): {
    repository: string
    branch: string
} {
    const first = repositories?.[0]
    return { repository: first?.name ?? '', branch: first?.initial_branch ?? '' }
}

/** The form field that shows an API validation error. The API reports the `repositories` list, and the form has two fields. */
export function formFieldForApiAttr(attr: string): string {
    if (!attr.startsWith('repositories')) {
        return attr
    }
    return attr.includes('initial_branch') ? 'branch' : 'repository'
}

export function toRepositories(repository: string, branch: string): CloudAgentRepositoryApi[] | null {
    const name = repository.trim()
    if (!name) {
        return null
    }
    return [{ name, initial_branch: branch.trim() || null }]
}

export function validateRepository(repository: string): string | undefined {
    return repository.trim() && !REPOSITORY_PATTERN.test(repository.trim())
        ? 'Use the form owner/name, for example acme/web'
        : undefined
}

export function validateIdleMinutes(minutes: number | null): string | undefined {
    if (minutes === null) {
        return undefined
    }
    return !Number.isInteger(minutes) || minutes < IDLE_MINUTES_MIN || minutes > IDLE_MINUTES_MAX
        ? `Use a whole number from ${IDLE_MINUTES_MIN} to ${IDLE_MINUTES_MAX}`
        : undefined
}

export function outputSchemaToText(schema: Record<string, unknown> | null | undefined): string {
    return schema ? JSON.stringify(schema, null, 2) : ''
}

/** Reads the schema text of a form. An empty text means no schema. */
export function parseOutputSchema(text: string): { schema: Record<string, unknown> | null; error?: string } {
    if (!text.trim()) {
        return { schema: null }
    }
    let parsed: unknown
    try {
        parsed = JSON.parse(text)
    } catch {
        return { schema: null, error: 'Enter valid JSON' }
    }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        return { schema: null, error: 'The schema must be a JSON object, for example {"type": "object"}' }
    }
    return { schema: parsed as Record<string, unknown> }
}

export function validateOutputSchema(text: string): string | undefined {
    return parseOutputSchema(text).error
}
