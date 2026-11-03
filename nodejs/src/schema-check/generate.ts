import { writeFileSync } from 'fs'
import path from 'path'
import { parseArgs } from 'util'

import { deriveSchemaRequirements } from './derive-requirements'
import { buildManifest } from './manifest'

const USAGE =
    'Usage: node nodejs/dist/schema-check/generate.js --repo-root PATH --output PATH [--source-commit SHA]\n' +
    'Writes the Django migrations this Node build needs, for nodejs/dist/schema-check/cli.js to check.'

function main(): number {
    const { values } = parseArgs({
        options: {
            'repo-root': { type: 'string' },
            output: { type: 'string' },
            'source-commit': { type: 'string' },
            help: { type: 'boolean' },
        },
    })
    if (values.help || !values['repo-root'] || !values.output) {
        console.error(USAGE)
        return values.help ? 0 : 2
    }

    const { requirements, tablesByApp } = deriveSchemaRequirements(path.resolve(values['repo-root']))
    if (requirements.length === 0) {
        console.error('Found no Django tables in nodejs/src. The source mounts are probably wrong.')
        return 1
    }

    const sourceCommit =
        values['source-commit'] && values['source-commit'] !== 'unknown' ? values['source-commit'] : null
    const manifest = buildManifest(requirements, sourceCommit)
    writeFileSync(values.output, JSON.stringify(manifest, null, 4) + '\n')

    console.log(`Wrote ${values.output} (digest ${manifest.digest}, ${requirements.length} apps)`)
    for (const requirement of requirements) {
        const tables = tablesByApp.get(requirement.app) ?? []
        console.log(`  ${requirement.app}.${requirement.migration}: ${tables.join(', ')}`)
    }
    return 0
}

process.exitCode = main()
