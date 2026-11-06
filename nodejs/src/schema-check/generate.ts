import { writeFileSync } from 'fs'
import path from 'path'
import { parseArgs } from 'util'

import { deriveSchemaRequirements } from './derive-requirements'
import { buildManifest } from './manifest'

const USAGE =
    'Usage: node nodejs/dist/schema-check/generate.js --repo-root PATH --output PATH [--source-commit SHA] [--strict]\n' +
    'Writes the Django migrations this Node build needs, for nodejs/dist/schema-check/cli.js to check.\n' +
    '--strict exits 1 when Node SQL reads a table that the check cannot cover. The image build runs without it and only\n' +
    'warns; the real-repo Jest test asserts the same rule in CI.'

function main(): number {
    const { values } = parseArgs({
        options: {
            'repo-root': { type: 'string' },
            output: { type: 'string' },
            'source-commit': { type: 'string' },
            strict: { type: 'boolean' },
            help: { type: 'boolean' },
        },
    })
    if (values.help || !values['repo-root'] || !values.output) {
        console.error(USAGE)
        return values.help ? 0 : 2
    }

    const { requirements, tablesByRequirement, findings } = deriveSchemaRequirements(path.resolve(values['repo-root']))
    if (!requirements.some((requirement) => requirement.kind === 'django')) {
        console.error('Found no Django tables in nodejs/src. The source mounts are probably wrong.')
        return 1
    }

    const sourceCommit =
        values['source-commit'] && values['source-commit'] !== 'unknown' ? values['source-commit'] : null
    const manifest = buildManifest(requirements, sourceCommit)
    writeFileSync(values.output, JSON.stringify(manifest, null, 4) + '\n')

    console.log(`Wrote ${values.output} (digest ${manifest.digest}, ${requirements.length} requirements)`)
    for (const requirement of requirements) {
        const key = requirement.kind === 'django' ? requirement.app : `sqlx:${requirement.database}`
        const target =
            requirement.kind === 'django'
                ? `${requirement.app}.${requirement.migration}`
                : `sqlx ${requirement.database} (${requirement.versions.length} versions, latest ${requirement.versions[requirement.versions.length - 1]})`
        console.log(`  ${target}: ${(tablesByRequirement.get(key) ?? []).join(', ')}`)
    }

    if (findings.length === 0) {
        return 0
    }
    console.error(`Node SQL reads ${findings.length} tables that the schema check cannot cover:`)
    findings.forEach((finding) => console.error(`  ${finding}`))
    return values.strict ? 1 : 0
}

process.exitCode = main()
