#!/usr/bin/env node
import fs from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const LEVELS = new Set(['Safe', 'Needs Review', 'Blocked'])
const MIGRATION_PATH = /^(?:posthog|ee|products)\/(?:[A-Za-z0-9_.-]+\/)*migrations\/[0-9][A-Za-z0-9_.-]*\.py$/

function fail(message) {
    throw new Error(`Invalid Depot migration report: ${message}`)
}

function readJson(file) {
    try {
        return JSON.parse(fs.readFileSync(file, 'utf8'))
    } catch (error) {
        fail(`${path.basename(file)} is not valid JSON: ${error.message}`)
    }
}

function text(value, name, limit) {
    if (typeof value !== 'string' || value.length > limit) {
        fail(`${name} must be a string no longer than ${limit} characters`)
    }
    if (/[\0-\x08\x0b\x0c\x0e-\x1f\x7f]/.test(value)) {
        fail(`${name} contains control characters`)
    }
    return value.replaceAll('\r\n', '\n').replaceAll('\r', '\n')
}

function integer(value, name, maximum) {
    if (!Number.isInteger(value) || value < 0 || value > maximum) {
        fail(`${name} must be an integer from 0 to ${maximum}`)
    }
    return value
}

function migrationPath(value, name) {
    const candidate = text(value, name, 500)
    if (!MIGRATION_PATH.test(candidate) || candidate.includes('..')) {
        fail(`${name} is not a repository migration path`)
    }
    return candidate
}

function inert(value) {
    return value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('@', '@\u200b')
}

function inlineText(value) {
    return inert(value).replace(/([\\`*_[\]{}()#+.!|>-])/g, '\\$1')
}

function codeBlock(value) {
    const safe = inert(value).replaceAll('\t', '    ')
    return safe
        .split('\n')
        .map((line) => `    ${line}`)
        .join('\n')
}

function timestamp(now) {
    return now.toISOString().slice(0, 16).replace('T', ' ') + ' UTC'
}

function validateAnalysis(value) {
    if (value === null) {
        return null
    }
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
        fail('risk analysis must be an object or null')
    }
    const summary = value.summary
    if (!summary || typeof summary !== 'object' || Array.isArray(summary)) {
        fail('risk analysis summary must be an object')
    }
    const counts = {
        safe: integer(summary.safe, 'safe migration count', 10000),
        needs_review: integer(summary.needs_review, 'needs-review migration count', 10000),
        blocked: integer(summary.blocked, 'blocked migration count', 10000),
    }
    if (!Array.isArray(value.migrations) || value.migrations.length > 10000) {
        fail('risk analysis migrations must be an array with at most 10000 entries')
    }
    const migrations = value.migrations.map((migration, index) => {
        if (!migration || typeof migration !== 'object' || Array.isArray(migration)) {
            fail(`risk migration ${index} must be an object`)
        }
        const level = text(migration.level, `risk migration ${index} level`, 32)
        if (!LEVELS.has(level)) {
            fail(`risk migration ${index} has an unknown level`)
        }
        return {
            label: text(migration.label, `risk migration ${index} label`, 300),
            level,
            filePath:
                migration.file_path === null
                    ? null
                    : migrationPath(migration.file_path, `risk migration ${index} file path`),
        }
    })
    const actual = {
        safe: migrations.filter(({ level }) => level === 'Safe').length,
        needs_review: migrations.filter(({ level }) => level === 'Needs Review').length,
        blocked: migrations.filter(({ level }) => level === 'Blocked').length,
    }
    if (Object.keys(counts).some((key) => counts[key] !== actual[key])) {
        fail('risk analysis summary does not match its migrations')
    }
    const maxLevel = value.max_level
    if (maxLevel !== null && !LEVELS.has(maxLevel)) {
        fail('risk analysis has an unknown maximum level')
    }
    const expectedMax = actual.blocked ? 'Blocked' : actual.needs_review ? 'Needs Review' : actual.safe ? 'Safe' : null
    if (maxLevel !== expectedMax) {
        fail('risk analysis maximum level does not match its migrations')
    }
    return { summary: counts, maxLevel, migrations }
}

function renderRisk(report, now, repository, headSha) {
    const exitCode = integer(report.exit_code, 'risk analyzer exit code', 255)
    const analysis = validateAnalysis(report.analysis)
    if (report.version !== 1) {
        fail('risk report version must be 1')
    }
    if (analysis === null) {
        return {
            body: 'Migration analysis failed. Check the Depot migration job logs for details.',
            conclusion: 'failure',
            title: 'Analyzer failed',
            exitCode,
            migrationCount: 0,
            maxLevel: null,
            analyzedPaths: [],
        }
    }

    const { safe, needs_review: needsReview, blocked } = analysis.summary
    const lines = [
        'We analyzed the migrations for potential risks.',
        '',
        `**Summary:** ${safe} Safe | ${needsReview} Needs Review | ${blocked} Blocked`,
    ]
    for (const level of ['Blocked', 'Needs Review', 'Safe']) {
        const migrations = analysis.migrations.filter((migration) => migration.level === level)
        if (!migrations.length) {
            continue
        }
        lines.push('', `## ${level}`)
        for (const migration of migrations) {
            const label = inlineText(migration.label)
            lines.push(migration.filePath ? `- ${label} (\`${migration.filePath}\`)` : `- ${label}`)
        }
    }
    lines.push(
        '',
        `*Last updated: ${timestamp(now)} ([${headSha.slice(0, 7)}](https://github.com/${repository}/commit/${headSha}))*`
    )

    const state = {
        Safe: ['success', 'All migrations safe'],
        'Needs Review': ['neutral', 'Migrations need review'],
        Blocked: ['failure', 'Blocked migrations'],
    }
    const [conclusion, title] =
        analysis.maxLevel === null ? ['success', 'No Django migrations to analyze'] : state[analysis.maxLevel]
    return {
        body: lines.join('\n'),
        conclusion,
        title,
        exitCode,
        migrationCount: analysis.migrations.length,
        maxLevel: analysis.maxLevel,
        analyzedPaths: analysis.migrations.flatMap(({ filePath }) => (filePath === null ? [] : [filePath])),
    }
}

export function renderReports({ inputDir, outputDir, repository, headSha, now = new Date() }) {
    if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repository)) {
        fail('repository is invalid')
    }
    if (!/^[a-f0-9]{40}$/.test(headSha)) {
        fail('head SHA is invalid')
    }

    const djangoSqlPath = path.join(inputDir, 'django-migration-sql.json')
    const djangoSqlAvailable = fs.existsSync(djangoSqlPath)
    const djangoSql = djangoSqlAvailable ? readJson(djangoSqlPath) : { version: 1, migrations: [] }
    if (djangoSql.version !== 1 || !Array.isArray(djangoSql.migrations) || djangoSql.migrations.length > 1000) {
        fail('Django SQL report has an invalid schema')
    }
    const djangoMigrations = djangoSql.migrations.map((migration, index) => {
        if (!migration || typeof migration !== 'object' || Array.isArray(migration)) {
            fail(`Django SQL migration ${index} must be an object`)
        }
        return {
            path: migrationPath(migration.path, `Django SQL migration ${index} path`),
            sql: text(migration.sql, `Django SQL migration ${index} SQL`, 100000),
        }
    })
    const djangoLines = djangoMigrations.length
        ? ['We detected new migrations in this pull request. Review the SQL output for each migration:', '']
        : ['No new Django migrations need SQL review.']
    for (const migration of djangoMigrations) {
        djangoLines.push(
            `#### [\`${migration.path}\`](https://github.com/${repository}/blob/${headSha}/${migration.path})`,
            '',
            codeBlock(migration.sql),
            ''
        )
    }
    if (djangoMigrations.length) {
        djangoLines.push(
            `*Last updated: ${timestamp(now)} ([${headSha.slice(0, 7)}](https://github.com/${repository}/commit/${headSha}))*`
        )
    }

    const riskPath = path.join(inputDir, 'django-migration-risk.json')
    const risk = renderRisk(
        fs.existsSync(riskPath) ? readJson(riskPath) : { version: 1, exit_code: 1, analysis: null },
        now,
        repository,
        headSha
    )

    const chPath = path.join(inputDir, 'ch-migration-sql.json')
    const chAvailable = fs.existsSync(chPath)
    const ch = chAvailable ? readJson(chPath) : { version: 1, count: 0, environments: [] }
    if (ch.version !== 1 || !Array.isArray(ch.environments) || ch.environments.length > 4) {
        fail('ClickHouse SQL report has an invalid schema')
    }
    const chCount = integer(ch.count, 'ClickHouse migration count', 1000)
    const allowedLabels = new Set(['unset', 'US', 'EU', 'DEV'])
    const seenLabels = new Set()
    const environments = ch.environments.map((environment, index) => {
        if (!environment || typeof environment !== 'object' || Array.isArray(environment)) {
            fail(`ClickHouse environment ${index} must be an object`)
        }
        const label = text(environment.label, `ClickHouse environment ${index} label`, 16)
        if (!allowedLabels.has(label) || seenLabels.has(label)) {
            fail(`ClickHouse environment ${index} has an invalid label`)
        }
        seenLabels.add(label)
        return { label, output: text(environment.output, `ClickHouse environment ${index} output`, 200000) }
    })
    if ((chCount === 0 && environments.length !== 0) || (chCount > 0 && environments.length !== 4)) {
        fail('ClickHouse environment count does not match the migration count')
    }
    const buckets = []
    for (const environment of environments) {
        const existing = buckets.find(({ output }) => output === environment.output)
        if (existing) {
            existing.labels.push(environment.label)
        } else {
            buckets.push({ labels: [environment.label], output: environment.output })
        }
    }
    const chLines = chCount ? ['## ClickHouse migration SQL per cloud environment', ''] : []
    if (buckets.length === 1) {
        chLines.push(
            '_Identical across all cloud environments (unset, US, EU, DEV)._',
            '',
            codeBlock(buckets[0].output)
        )
    } else {
        for (const bucket of buckets) {
            chLines.push(`### ${bucket.labels.join(', ')}`, '', codeBlock(bucket.output), '')
        }
    }

    fs.mkdirSync(outputDir, { recursive: true })
    fs.writeFileSync(path.join(outputDir, 'django-migration-sql.md'), `${djangoLines.join('\n').trim()}\n`)
    fs.writeFileSync(path.join(outputDir, 'django-migration-risk.md'), `${risk.body.trim()}\n`)
    fs.writeFileSync(path.join(outputDir, 'migration-risk-check.md'), `${risk.body.trim()}\n`)
    fs.writeFileSync(path.join(outputDir, 'ch-migration-sql.md'), `${chLines.join('\n').trim()}\n`)
    fs.writeFileSync(
        path.join(outputDir, 'metadata.json'),
        `${JSON.stringify({
            djangoSqlAvailable,
            djangoMigrationCount: djangoMigrations.length,
            riskExitCode: risk.exitCode,
            riskMigrationCount: risk.migrationCount,
            riskMaxLevel: risk.maxLevel,
            riskConclusion: risk.conclusion,
            riskTitle: risk.title,
            analyzedPaths: risk.analyzedPaths,
            chAvailable,
            chMigrationCount: chCount,
        })}\n`
    )
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    const [inputDir, outputDir, repository, headSha] = process.argv.slice(2)
    if (!inputDir || !outputDir || !repository || !headSha) {
        console.error(
            'Usage: render-depot-migration-report.mjs <input directory> <output directory> <repository> <head SHA>'
        )
        process.exit(1)
    }
    renderReports({ inputDir, outputDir, repository, headSha })
}
