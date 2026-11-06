#!/usr/bin/env node
import Ajv from 'ajv'
import standaloneCode from 'ajv/dist/standalone/index.js'
import fs from 'fs'

const inputPath = 'src/queries/schema.json'
// esbuild ships a module whole into one chunk. The web analytics scene parses its URL filters with two
// small validators, so they live in their own module, apart from the large ones other scenes use.
const outputs = {
    'src/queries/validators.js': ['AnyPropertyFilter', 'SessionPropertyFilter', 'ExperimentMetric'],
    'src/queries/web-analytics-validators.js': ['WebAnalyticsPropertyFilters', 'CompareFilter'],
}

// Load the schema
const schema = JSON.parse(fs.readFileSync(inputPath, 'utf-8'))

// Create AJV instance and compile schemas
const ajv = new Ajv({
    allowUnionTypes: true,
    code: { source: true, esm: true },
    // `discriminator` is an OpenAPI keyword used by ts-json-schema-generator (and consumed
    // by datamodel-codegen to emit Pydantic `Field(discriminator=...)`). It carries routing
    // information for union types, not validation rules — declare it as a no-op so ajv's
    // strict mode doesn't reject schemas that use it.
    keywords: [{ keyword: 'discriminator' }],
})

// Add the main schema
ajv.addSchema(schema)

for (const [outputPath, validators] of Object.entries(outputs)) {
    // standaloneCode needs the schema references, not the compiled functions
    const schemaRefs = {}
    for (const name of validators) {
        schemaRefs[name] = `#/definitions/${name}`
    }

    const moduleCode = standaloneCode(ajv, schemaRefs)

    fs.writeFileSync(
        outputPath,
        `// AUTO-GENERATED FILE - DO NOT EDIT DIRECTLY
${moduleCode}
`
    )
}
