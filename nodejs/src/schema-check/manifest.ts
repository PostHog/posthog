import { createHash } from 'crypto'
import { existsSync, readFileSync } from 'fs'
import path from 'path'

import { parseJSON } from '~/common/utils/json-parse'

export const MANIFEST_SCHEMA_VERSION = 1

// Resolves to /code/nodejs/schema-requirements.json in the Node image, next to nodejs/dist.
export const DEFAULT_MANIFEST_PATH = path.resolve(__dirname, '..', '..', 'schema-requirements.json')

export interface MigrationRequirement {
    database: 'default'
    app: string
    migration: string
    // Set when `migration` is a squash. Django can record either the squash or every migration it replaces.
    replaces?: string[]
}

export interface SchemaRequirementsManifest {
    schema_version: number
    source_commit: string | null
    digest: string
    requirements: MigrationRequirement[]
}

export class ManifestError extends Error {}

export function computeRequirementsDigest(requirements: MigrationRequirement[]): string {
    return createHash('sha256').update(JSON.stringify(requirements)).digest('hex').slice(0, 12)
}

export function buildManifest(
    requirements: MigrationRequirement[],
    sourceCommit: string | null
): SchemaRequirementsManifest {
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

function parseRequirement(value: unknown, index: number): MigrationRequirement {
    const item = value as Record<string, unknown> | null
    if (typeof item !== 'object' || item === null) {
        throw new ManifestError(`requirements[${index}] is not an object`)
    }
    if (item.database !== 'default') {
        throw new ManifestError(`requirements[${index}].database must be "default"`)
    }
    if (typeof item.app !== 'string' || !item.app || typeof item.migration !== 'string' || !item.migration) {
        throw new ManifestError(`requirements[${index}] needs a non-empty app and migration`)
    }
    if (item.replaces !== undefined && !isStringArray(item.replaces)) {
        throw new ManifestError(`requirements[${index}].replaces must be a list of migration names`)
    }
    const requirement: MigrationRequirement = { database: 'default', app: item.app, migration: item.migration }
    if (item.replaces !== undefined) {
        requirement.replaces = item.replaces
    }
    return requirement
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
    // An empty list means the generator found nothing, which is a broken build and not "no requirements".
    if (data.requirements.length === 0) {
        throw new ManifestError('manifest requirements list is empty')
    }

    return {
        schema_version: MANIFEST_SCHEMA_VERSION,
        source_commit: typeof data.source_commit === 'string' ? data.source_commit : null,
        digest: typeof data.digest === 'string' ? data.digest : '',
        requirements: data.requirements.map(parseRequirement),
    }
}

export function readManifest(manifestPath: string): SchemaRequirementsManifest {
    if (!existsSync(manifestPath)) {
        throw new ManifestError(`manifest not found at ${manifestPath}`)
    }
    return parseManifest(readFileSync(manifestPath, 'utf8'))
}
