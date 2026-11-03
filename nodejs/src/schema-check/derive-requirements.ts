import { existsSync, readFileSync, readdirSync } from 'fs'
import path from 'path'

import { MigrationRequirement } from './manifest'

// Top-level trees that hold Django apps. Dockerfile.node bind-mounts the same trees into the generator step.
export const DJANGO_SOURCE_ROOTS = ['posthog', 'ee', 'products']

// ClickHouse migrations are not Django apps and do not write to django_migrations in Postgres.
const EXCLUDED_MIGRATION_DIRS = ['posthog/clickhouse/migrations']

const PRODUCT_DB_ROUTING_FILE = 'products/db_routing.yaml'
const NODEJS_SOURCE_DIR = 'nodejs/src'

const SKIPPED_DIR_NAMES = new Set(['node_modules', '__pycache__', 'dist', 'frontend'])

const MIGRATION_FILE = /^\d{4}_\w+\.py$/
const CREATE_MODEL_NAME = /CreateModel\(\s*name\s*=\s*['"](\w+)['"]/g
const DB_TABLE_OPTION = /['"]db_table['"]\s*:\s*['"](\w+)['"]/g
const TABLE_ARGUMENT = /\b(?:db_)?table\s*=\s*['"](\w+)['"]/g
const APP_CONFIG_LABEL = /^\s*label\s*=\s*['"](\w+)['"]/m
const APP_CONFIG_NAME = /^\s*name\s*=\s*['"]([\w.]+)['"]/m
const SQUASH_REPLACES = /^\s*replaces\s*=\s*\[([\s\S]*?)\]/m
const MIGRATION_KEY = /\(\s*['"](\w+)['"]\s*,\s*['"](\w+)['"]\s*\)/g
const ROUTED_APP_LABEL = /app_label:\s*['"]?(\w+)['"]?/g
const LOWERCASE_IDENTIFIER = /\b[a-z][a-z0-9_]+\b/g

export interface DjangoApp {
    label: string
    migrationsDir: string
    leafMigration: string
}

export interface DerivedSchemaRequirements {
    requirements: MigrationRequirement[]
    tablesByApp: Map<string, string[]>
}

function listFilesRecursively(dir: string, keep: (fileName: string) => boolean): string[] {
    if (!existsSync(dir)) {
        return []
    }
    const files: string[] = []
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
        if (entry.name.startsWith('.') || SKIPPED_DIR_NAMES.has(entry.name)) {
            continue
        }
        const fullPath = path.join(dir, entry.name)
        if (entry.isDirectory()) {
            files.push(...listFilesRecursively(fullPath, keep))
        } else if (entry.isFile() && keep(entry.name)) {
            files.push(fullPath)
        }
    }
    return files
}

function matchAll(text: string, pattern: RegExp): string[] {
    return Array.from(text.matchAll(pattern), (match) => match[1])
}

// Mirrors Django: AppConfig.label wins, then the last part of AppConfig.name, then the package directory name.
export function readAppLabel(appDir: string): string {
    const appsPy = path.join(appDir, 'apps.py')
    if (existsSync(appsPy)) {
        const text = readFileSync(appsPy, 'utf8')
        const label = text.match(APP_CONFIG_LABEL)?.[1]
        if (label) {
            return label
        }
        const name = text.match(APP_CONFIG_NAME)?.[1]
        if (name) {
            return name.split('.').pop()!
        }
    }
    return path.basename(appDir)
}

export function findDjangoApps(repoRoot: string): DjangoApp[] {
    const excluded = new Set(EXCLUDED_MIGRATION_DIRS.map((dir) => path.join(repoRoot, dir)))
    const maxMigrationFiles = DJANGO_SOURCE_ROOTS.flatMap((root) =>
        listFilesRecursively(path.join(repoRoot, root), (name) => name === 'max_migration.txt')
    )

    const apps: DjangoApp[] = []
    for (const maxMigrationFile of maxMigrationFiles) {
        const migrationsDir = path.dirname(maxMigrationFile)
        if (path.basename(migrationsDir) !== 'migrations' || excluded.has(migrationsDir)) {
            continue
        }
        const leafMigration = readFileSync(maxMigrationFile, 'utf8').trim()
        if (!existsSync(path.join(migrationsDir, `${leafMigration}.py`))) {
            throw new Error(`${maxMigrationFile} names ${leafMigration}, but ${leafMigration}.py does not exist`)
        }
        apps.push({ label: readAppLabel(path.dirname(migrationsDir)), migrationsDir, leafMigration })
    }
    return apps
}

export function readProductRoutedLabels(repoRoot: string): Set<string> {
    const routingFile = path.join(repoRoot, PRODUCT_DB_ROUTING_FILE)
    if (!existsSync(routingFile)) {
        return new Set()
    }
    return new Set(matchAll(readFileSync(routingFile, 'utf8'), ROUTED_APP_LABEL))
}

// A table belongs to every app whose migrations name it, so a model moved between apps puts both apps in scope.
export function collectTableOwners(apps: DjangoApp[]): Map<string, Set<string>> {
    const owners = new Map<string, Set<string>>()
    const addOwner = (table: string, label: string): void => {
        const labels = owners.get(table) ?? new Set<string>()
        labels.add(label)
        owners.set(table, labels)
    }

    for (const app of apps) {
        const migrationFiles = readdirSync(app.migrationsDir).filter((name) => MIGRATION_FILE.test(name))
        for (const fileName of migrationFiles) {
            const text = readFileSync(path.join(app.migrationsDir, fileName), 'utf8')
            for (const modelName of matchAll(text, CREATE_MODEL_NAME)) {
                addOwner(`${app.label}_${modelName.toLowerCase()}`, app.label)
            }
            for (const table of [...matchAll(text, DB_TABLE_OPTION), ...matchAll(text, TABLE_ARGUMENT)]) {
                addOwner(table, app.label)
            }
        }
    }
    return owners
}

// The scan does not know which database a query uses. Node writes posthog_cohortpeople through the persons
// database, but the match still puts the cohorts app in scope, so a new cohorts migration holds Node deploys
// until Django applies it. This is a known false positive and it only adds wait time.
export function collectNodeIdentifiers(nodeSourceDir: string): Set<string> {
    const sourceFiles = listFilesRecursively(
        nodeSourceDir,
        (name) => name.endsWith('.ts') && !name.includes('.test.')
    ).filter((file) => !file.split(path.sep).includes('__tests__'))

    const identifiers = new Set<string>()
    for (const file of sourceFiles) {
        for (const identifier of readFileSync(file, 'utf8').match(LOWERCASE_IDENTIFIER) ?? []) {
            identifiers.add(identifier)
        }
    }
    return identifiers
}

export function readSquashReplaces(app: DjangoApp): string[] | undefined {
    const text = readFileSync(path.join(app.migrationsDir, `${app.leafMigration}.py`), 'utf8')
    const replacesBlock = text.match(SQUASH_REPLACES)?.[1]
    if (replacesBlock === undefined) {
        return undefined
    }

    const names: string[] = []
    for (const [, replacedApp, replacedName] of replacesBlock.matchAll(MIGRATION_KEY)) {
        // The check compares names within one app, so a cross-app replaces entry would be checked against the wrong app.
        if (replacedApp !== app.label) {
            throw new Error(
                `${app.label}.${app.leafMigration} replaces ${replacedApp}.${replacedName}, which is in another app`
            )
        }
        names.push(replacedName)
    }
    return names
}

export function deriveSchemaRequirements(repoRoot: string): DerivedSchemaRequirements {
    const routedLabels = readProductRoutedLabels(repoRoot)
    const apps = findDjangoApps(repoRoot).filter((app) => !routedLabels.has(app.label))
    const tableOwners = collectTableOwners(apps)
    const nodeIdentifiers = collectNodeIdentifiers(path.join(repoRoot, NODEJS_SOURCE_DIR))

    const tablesByApp = new Map<string, string[]>()
    for (const table of [...tableOwners.keys()].sort()) {
        if (!nodeIdentifiers.has(table)) {
            continue
        }
        for (const label of tableOwners.get(table)!) {
            tablesByApp.set(label, [...(tablesByApp.get(label) ?? []), table])
        }
    }

    const requirements: MigrationRequirement[] = apps
        .filter((app) => tablesByApp.has(app.label))
        .sort((a, b) => a.label.localeCompare(b.label))
        .map((app) => {
            const requirement: MigrationRequirement = {
                database: 'default',
                app: app.label,
                migration: app.leafMigration,
            }
            const replaces = readSquashReplaces(app)
            if (replaces !== undefined) {
                requirement.replaces = replaces
            }
            return requirement
        })

    return { requirements, tablesByApp }
}
