import { createHash } from 'crypto'
import { existsSync, readFileSync } from 'fs'
import path from 'path'

import { parseJSON } from '~/common/utils/json-parse'

export const MANIFEST_SCHEMA_VERSION = 1

// Resolves to /code/nodejs/schema-requirements.json in the Node image, next to nodejs/dist.
export const DEFAULT_MANIFEST_PATH = path.resolve(__dirname, '..', '..', 'schema-requirements.json')

// The names match the arguments of rust/bin/migrate-entry, which the sqlx-migrate deploy runs per database.
export const SQLX_DATABASES = ['persons', 'cyclotron-node', 'behavioral-cohorts'] as const
export type SqlxDatabase = (typeof SQLX_DATABASES)[number]

export interface DjangoRequirement {
    kind: 'django'
    database: 'default'
    app: string
    migration: string
    // Set when `migration` is a squash. Django can record either the squash or every migration it replaces.
    replaces?: string[]
}

export interface SqlxRequirement {
    kind: 'sqlx'
    database: SqlxDatabase
    // Every version in the migration directory, ascending. A version is the timestamp in the file name, so a
    // late merge can add a version below the highest one, and `sqlx migrate run` still applies it.
    versions: number[]
}

export type Requirement = DjangoRequirement | SqlxRequirement

export interface SchemaRequirementsManifest {
    schema_version: number
    source_commit: string | null
    // Identifies the requirement list in logs. Consumers do not recompute it, because JSON.stringify output is not canonical across languages.
    digest: string
    requirements: Requirement[]
}

export class ManifestError extends Error {}

export function computeRequirementsDigest(requirements: Requirement[]): string {
    return createHash('sha256').update(JSON.stringify(requirements)).digest('hex').slice(0, 12)
}

export function buildManifest(requirements: Requirement[], sourceCommit: string | null): SchemaRequirementsManifest {
    return {
        schema_version: MANIFEST_SCHEMA_VERSION,
        source_commit: sourceCommit,
        digest: computeRequirementsDigest(requirements),
        requirements,
    }
}

function isStringArray(value: unknown): value is string[] {
    return Array.isArray(value) && value.every((item) => typeof item === 'string' && item.length > 0)
}

function parseDjangoRequirement(item: Record<string, unknown>, index: number): DjangoRequirement {
    if (item.database !== 'default') {
        throw new ManifestError(`requirements[${index}].database must be "default"`)
    }
    if (typeof item.app !== 'string' || !item.app || typeof item.migration !== 'string' || !item.migration) {
        throw new ManifestError(`requirements[${index}] needs a non-empty app and migration`)
    }
    if (item.replaces !== undefined && !isStringArray(item.replaces)) {
        throw new ManifestError(`requirements[${index}].replaces must be a list of migration names`)
    }
    const requirement: DjangoRequirement = {
        kind: 'django',
        database: 'default',
        app: item.app,
        migration: item.migration,
    }
    if (item.replaces !== undefined) {
        requirement.replaces = item.replaces
    }
    return requirement
}

function parseSqlxRequirement(item: Record<string, unknown>, index: number): SqlxRequirement {
    const database = SQLX_DATABASES.find((name) => name === item.database)
    if (!database) {
        throw new ManifestError(`requirements[${index}].database must be one of ${SQLX_DATABASES.join(', ')}`)
    }
    const versions = item.versions
    if (
        !Array.isArray(versions) ||
        versions.length === 0 ||
        !versions.every((version) => typeof version === 'number' && Number.isSafeInteger(version) && version > 0)
    ) {
        throw new ManifestError(`requirements[${index}].versions must be a non-empty list of positive integers`)
    }
    return { kind: 'sqlx', database, versions: [...new Set<number>(versions)].sort((a, b) => a - b) }
}

// An unknown kind is an error. Skipping it would report a pass for a requirement that nothing checked.
function parseRequirement(value: unknown, index: number): Requirement {
    const item = value as Record<string, unknown> | null
    if (typeof item !== 'object' || item === null) {
        throw new ManifestError(`requirements[${index}] is not an object`)
    }
    if (item.kind === 'django') {
        return parseDjangoRequirement(item, index)
    }
    if (item.kind === 'sqlx') {
        return parseSqlxRequirement(item, index)
    }
    throw new ManifestError(`requirements[${index}].kind must be "django" or "sqlx", got ${JSON.stringify(item.kind)}`)
}

export function parseManifest(text: string): SchemaRequirementsManifest {
    let raw: unknown
    try {
        raw = parseJSON(text)
    } catch (error) {
        throw new ManifestError(`manifest is not valid JSON: ${error.message}`)
    }

    const data = raw as Record<string, unknown> | null
    if (typeof data !== 'object' || data === null) {
        throw new ManifestError('manifest is not a JSON object')
    }
    if (data.schema_version !== MANIFEST_SCHEMA_VERSION) {
        throw new ManifestError(
            `manifest schema_version is ${JSON.stringify(data.schema_version)}, expected ${MANIFEST_SCHEMA_VERSION}`
        )
    }
    if (!Array.isArray(data.requirements)) {
        throw new ManifestError('manifest has no requirements list')
    }
    const requirements = data.requirements.map(parseRequirement)
    // No Django entry means the generator found nothing, which is a broken build and not "no requirements".
    if (!requirements.some((requirement) => requirement.kind === 'django')) {
        throw new ManifestError('manifest has no Django requirements')
    }

    return {
        schema_version: MANIFEST_SCHEMA_VERSION,
        source_commit: typeof data.source_commit === 'string' ? data.source_commit : null,
        digest: typeof data.digest === 'string' ? data.digest : '',
        requirements,
    }
}

export function djangoRequirements(manifest: SchemaRequirementsManifest): DjangoRequirement[] {
    return manifest.requirements.filter(
        (requirement): requirement is DjangoRequirement => requirement.kind === 'django'
    )
}

export function sqlxRequirements(manifest: SchemaRequirementsManifest): SqlxRequirement[] {
    return manifest.requirements.filter((requirement): requirement is SqlxRequirement => requirement.kind === 'sqlx')
}

export function readManifest(manifestPath: string): SchemaRequirementsManifest {
    if (!existsSync(manifestPath)) {
        throw new ManifestError(`manifest not found at ${manifestPath}`)
    }
    return parseManifest(readFileSync(manifestPath, 'utf8'))
}
