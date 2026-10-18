#!/usr/bin/env node
import { Validator } from 'ata-validator'
import { toStandaloneModule } from 'ata-validator/aot'
import fs from 'fs'

const inputPath = 'src/queries/schema.json'
const outputPath = 'src/queries/validators.js'

// Load the schema
const schema = JSON.parse(fs.readFileSync(inputPath, 'utf-8'))

// Define the validators we need
const validators = [
    'AnyPropertyFilter',
    'WebAnalyticsPropertyFilters',
    'SessionPropertyFilter',
    'CompareFilter',
    'ExperimentMetric',
]

// Each validator is compiled to a module that imports nothing. schema-guards.ts only reads
// the boolean, so `abortEarly` leaves the error messages out. `discriminator` (an OpenAPI
// keyword from ts-json-schema-generator, consumed by datamodel-codegen) carries no
// validation rules; ata treats unknown keywords as annotations, so it needs no declaration.
const MODULE_EXPORTS =
    /\nexport \{ validate, isValid, schemaHash, ataVersion \};\nexport default \{ validate, isValid, schemaHash, ataVersion \};\n$/

let banner = ''
const blocks = validators.map((name) => {
    const source = toStandaloneModule(new Validator({ ...schema, $ref: `#/definitions/${name}` }), { abortEarly: true })
    // Fail the build rather than write a file that does not export what schema-guards.ts calls.
    if (!MODULE_EXPORTS.test(source)) {
        throw new Error(`build-validators: unexpected module shape from ata-validator for ${name}`)
    }
    const lines = source.replace(MODULE_EXPORTS, '').split('\n')
    // The module's leading comments name the ata version that wrote it. Keep them once.
    const comments = []
    while (lines[0].startsWith('//')) {
        comments.push(lines.shift())
    }
    banner = comments.join('\n')
    // Each module in a function of its own, so the five share one file without name clashes.
    return `export const ${name} = /* @__PURE__ */ (() => {\n${lines.join('\n')}\nreturn isValid\n})()\n`
})

// Write the output
const output = `// AUTO-GENERATED FILE - DO NOT EDIT DIRECTLY
${banner}
${blocks.join('\n')}`

fs.writeFileSync(outputPath, output)
