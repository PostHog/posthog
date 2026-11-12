import { existsSync, readFileSync, readdirSync } from 'fs'
import path from 'path'

import { DjangoRequirement, Requirement, SQLX_DATABASES, SqlxDatabase, SqlxRequirement } from './manifest'

// Top-level trees that hold Django apps. Dockerfile.node bind-mounts the same trees into the generator step.
export const DJANGO_SOURCE_ROOTS = ['posthog', 'ee', 'products']

// ClickHouse migrations are not Django apps and do not write to django_migrations in Postgres.
const EXCLUDED_MIGRATION_DIRS = ['posthog/clickhouse/migrations']

const PRODUCT_DB_ROUTING_FILE = 'products/db_routing.yaml'

// rust/Dockerfile.sqlx-migrate copies these directories, and the sqlx-migrate deploy applies them.
export const SQLX_MIGRATION_DIRS: Record<SqlxDatabase, string> = {
    persons: 'rust/persons_migrations',
    'cyclotron-node': 'rust/cyclotron-node-migrations',
    'behavioral-cohorts': 'rust/behavioral_cohorts_migrations',
}
const NODEJS_SOURCE_DIR = 'nodejs/src'

const SKIPPED_DIR_NAMES = new Set(['node_modules', '__pycache__', 'dist', 'frontend'])

const MIGRATION_FILE = /^\d{4}_\w+\.py$/
// sqlx takes the version from the file name prefix. A .down.sql file reverts its .up.sql twin and adds no version.
const SQLX_MIGRATION_FILE = /^(\d+)_(?!.*\.down\.sql$).+\.sql$/
// The lookahead stops a backtrack from taking IF as the name, for example in `CREATE TABLE IF NOT EXISTS {name}`.
const CREATE_TABLE = /\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?"?(?!(?:if|only)\b)(\w+)"?/gi
const CREATE_MODEL_NAME = /CreateModel\(\s*name\s*=\s*['"](\w+)['"]/g
const RENAME_MODEL_CALL = /RenameModel\(([^)]*)\)/g
const NEW_NAME_ARGUMENT = /\bnew_name\s*=\s*['"](\w+)['"]/
const DB_TABLE_OPTION = /['"]db_table['"]\s*:\s*['"](\w+)['"]/g
const TABLE_ARGUMENT = /\b(?:db_)?table\s*=\s*['"](\w+)['"]/g
const APP_CONFIG_LABEL = /^\s*label\s*=\s*['"](\w+)['"]/m
const APP_CONFIG_NAME = /^\s*name\s*=\s*['"]([\w.]+)['"]/m
const SQUASH_REPLACES = /^\s*replaces\s*=\s*\[([\s\S]*?)\]/m
const MIGRATION_KEY = /\(\s*['"](\w+)['"]\s*,\s*['"](\w+)['"]\s*\)/g
const ROUTED_APP_LABEL = /app_label:\s*['"]?(\w+)['"]?/g
const LOWERCASE_IDENTIFIER = /\b[a-z][a-z0-9_]+\b/g
const SQL_TABLE_NAME = String.raw`(?:"?public"?\.)?"?(?!(?:if|only)\b)[a-z_]\w*"?`
const SQL_TABLE_REFERENCE = new RegExp(
    String.raw`\b(?:FROM|JOIN|INTO|UPDATE|TABLE|TRUNCATE)\s+(?:ONLY\s+)?(?:IF\s+(?:NOT\s+)?EXISTS\s+)?` +
        String.raw`((?:${SQL_TABLE_NAME}(?:\s+(?:AS\s+)?"?\w+"?)?\s*,\s*)*${SQL_TABLE_NAME})`,
    'gi'
)
const SQL_TABLE_LIST_ITEM = new RegExp(String.raw`^\s*(${SQL_TABLE_NAME})`, 'i')
// Whole comment lines only: prose reuses SQL keywords, and a `//` inside a SQL string must not cut the query.
const TS_COMMENT_LINE = /^\s*(?:\/\/.*|\/\*(?:(?!\*\/)[\s\S])*\*\/)$/gm
// ClickHouse tables share app prefixes, so a file that names ClickHouse and no Postgres client gives no findings.
const POSTGRES_CLIENT_USE = /\bPostgresUse\b|\bPostgresRouter\b|\bTransactionClient\b|\bLazyPool\b|from 'pg'/
const CLICKHOUSE_USE = /clickhouse/i

export interface DjangoApp {
    label: string
    migrationsDir: string
    leafMigration: string
}

export interface DerivedSchemaRequirements {
    requirements: Requirement[]
    // Keyed by Django app label, or by "sqlx:<database>" for sqlx requirements.
    tablesByRequirement: Map<string, string[]>
    findings: string[]
}

export interface SqlxMigrationDir {
    database: SqlxDatabase
    identifiersByVersion: Map<number, Set<string>>
    tables: Set<string>
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
            const renamedModels = matchAll(text, RENAME_MODEL_CALL).flatMap(
                (call) => call.match(NEW_NAME_ARGUMENT)?.[1] ?? []
            )
            for (const modelName of [...matchAll(text, CREATE_MODEL_NAME), ...renamedModels]) {
                addOwner(`${app.label}_${modelName.toLowerCase()}`, app.label)
            }
            const tables = [...matchAll(text, DB_TABLE_OPTION), ...matchAll(text, TABLE_ARGUMENT)]
            // A RunSQL can create a table. Prose like "a CREATE TABLE would ..." has no underscore, unlike a Django table.
            const rawSqlTables = matchAll(text, CREATE_TABLE)
                .map((name) => name.toLowerCase())
                .filter((name) => name.includes('_'))
            for (const table of [...tables, ...rawSqlTables]) {
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

export interface NodeSqlTables {
    all: Set<string>
    // Without the files that only query ClickHouse.
    postgres: Set<string>
}

export function collectNodeSqlTables(nodeSourceDir: string): NodeSqlTables {
    const sourceFiles = listFilesRecursively(
        nodeSourceDir,
        (name) => name.endsWith('.ts') && !name.includes('.test.')
    ).filter((file) => !file.split(path.sep).includes('__tests__'))

    const tables: NodeSqlTables = { all: new Set(), postgres: new Set() }
    for (const file of sourceFiles) {
        const code = readFileSync(file, 'utf8').replace(TS_COMMENT_LINE, '')
        const clickhouseOnly = CLICKHOUSE_USE.test(code) && !POSTGRES_CLIENT_USE.test(code)
        for (const list of matchAll(code, SQL_TABLE_REFERENCE)) {
            for (const item of list.split(',')) {
                const name = item.match(SQL_TABLE_LIST_ITEM)?.[1] ?? ''
                const table = name
                    .replace(/"/g, '')
                    .replace(/^public\./i, '')
                    .toLowerCase()
                tables.all.add(table)
                if (!clickhouseOnly) {
                    tables.postgres.add(table)
                }
            }
        }
    }
    return tables
}

// Flags routed tables (product database, not checked) and prefixed tables no scanned migration creates.
export function findUncoveredTables(
    nodeSqlTables: Set<string>,
    tableOwners: Map<string, Set<string>>,
    routedTableOwners: Map<string, Set<string>>,
    sqlxTables: Set<string>,
    appLabels: string[]
): string[] {
    const findings: string[] = []
    for (const table of [...nodeSqlTables].sort()) {
        // A model moved into a routed app can keep its old db_table, so a routed owner wins over an old one.
        const routedOwners = routedTableOwners.get(table)
        if (routedOwners) {
            findings.push(
                `${table}: owned by ${[...routedOwners].sort().join(', ')}, which products/db_routing.yaml sends to a product database`
            )
            continue
        }
        if (tableOwners.has(table) || sqlxTables.has(table)) {
            continue
        }
        const prefixLabel = appLabels.find((label) => table.startsWith(`${label}_`))
        if (prefixLabel) {
            findings.push(`${table}: no scanned migration creates it, although its name starts with ${prefixLabel}_`)
        }
    }
    return findings
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

// A missing directory throws, because a wrong bind mount in Dockerfile.node must fail the build and not drop the requirement.
export function readSqlxMigrationDir(repoRoot: string, database: SqlxDatabase): SqlxMigrationDir {
    const dir = path.join(repoRoot, SQLX_MIGRATION_DIRS[database])
    if (!existsSync(dir)) {
        throw new Error(`${dir} does not exist`)
    }
    const identifiersByVersion = new Map<number, Set<string>>()
    const tables = new Set<string>()
    for (const fileName of readdirSync(dir)) {
        const version = fileName.match(SQLX_MIGRATION_FILE)?.[1]
        if (version === undefined) {
            continue
        }
        const sql = readFileSync(path.join(dir, fileName), 'utf8')
        identifiersByVersion.set(Number(version), new Set(sql.toLowerCase().match(LOWERCASE_IDENTIFIER)))
        for (const table of matchAll(sql, CREATE_TABLE)) {
            tables.add(table.toLowerCase())
        }
    }
    if (identifiersByVersion.size === 0) {
        throw new Error(`${dir} has no sqlx migrations`)
    }
    return { database, identifiersByVersion, tables }
}

export function deriveSchemaRequirements(repoRoot: string): DerivedSchemaRequirements {
    const routedLabels = readProductRoutedLabels(repoRoot)
    const allApps = findDjangoApps(repoRoot)
    const apps = allApps.filter((app) => !routedLabels.has(app.label))
    const tableOwners = collectTableOwners(apps)
    const nodeSqlTables = collectNodeSqlTables(path.join(repoRoot, NODEJS_SOURCE_DIR))
    // Postgres folds unquoted names to lowercase, so `FROM POSTHOG_TEAM` reads posthog_team too.
    const nodeIdentifiers = new Set([
        ...collectNodeIdentifiers(path.join(repoRoot, NODEJS_SOURCE_DIR)),
        ...nodeSqlTables.all,
    ])

    const tablesByRequirement = new Map<string, string[]>()
    for (const table of [...tableOwners.keys()].sort()) {
        if (!nodeIdentifiers.has(table)) {
            continue
        }
        for (const label of tableOwners.get(table)!) {
            tablesByRequirement.set(label, [...(tablesByRequirement.get(label) ?? []), table])
        }
    }

    const djangoRequirements: DjangoRequirement[] = apps
        .filter((app) => tablesByRequirement.has(app.label))
        .sort((a, b) => a.label.localeCompare(b.label))
        .map((app) => {
            const requirement: DjangoRequirement = {
                kind: 'django',
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

    const sqlxRequirements: SqlxRequirement[] = []
    const sqlxTables = new Set<string>()
    for (const database of SQLX_DATABASES) {
        const migrationDir = readSqlxMigrationDir(repoRoot, database)
        migrationDir.tables.forEach((table) => sqlxTables.add(table))
        const tables = [...migrationDir.tables].filter((table) => nodeIdentifiers.has(table)).sort()
        if (tables.length === 0) {
            continue
        }
        tablesByRequirement.set(`sqlx:${database}`, tables)
        // A version is skipped only when every table it names is one Node does not read, for example a drop
        // of a table whose Node reader is gone. A version that names no table, such as `DROP INDEX <name>`,
        // can still change how Node's queries behave, so it stays required.
        const versions = [...migrationDir.identifiersByVersion]
            .filter(([, identifiers]) => {
                const namedTables = [...migrationDir.tables].filter((table) => identifiers.has(table))
                return namedTables.length === 0 || namedTables.some((table) => tables.includes(table))
            })
            .map(([version]) => version)
            .sort((a, b) => a - b)
        sqlxRequirements.push({ kind: 'sqlx', database, versions })
    }

    const findings = findUncoveredTables(
        nodeSqlTables.postgres,
        tableOwners,
        collectTableOwners(allApps.filter((app) => routedLabels.has(app.label))),
        sqlxTables,
        allApps.map((app) => app.label)
    )

    return { requirements: [...djangoRequirements, ...sqlxRequirements], tablesByRequirement, findings }
}
