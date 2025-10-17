#!/usr/bin/env node
import Ajv from 'ajv'
import standaloneCode from 'ajv/dist/standalone/index.js'
import fs from 'fs'

const inputPath = 'src/queries/schema.json'
const outputPath = 'src/queries/validators.js'

// Load the schema
const schema = JSON.parse(fs.readFileSync(inputPath, 'utf-8'))

// Create AJV instance and compile schemas
const ajv = new Ajv({
    allowUnionTypes: true,
    code: { source: true, esm: true },
})

// Add the main schema
ajv.addSchema(schema)

// Define the validators we need
const validators = [
    'AnyPropertyFilter',
    'WebAnalyticsPropertyFilters',
    'RevenueAnalyticsPropertyFilters',
    'SessionPropertyFilter',
    'CompareFilter',
]

// Compile validators - standaloneCode needs the schema references, not the compiled functions
const schemaRefs = {}
for (const name of validators) {
    schemaRefs[name] = `#/definitions/${name}`
}

// Generate standalone code
const moduleCode = standaloneCode(ajv, schemaRefs)

// Write the output
const output = `// AUTO-GENERATED FILE - DO NOT EDIT DIRECTLY
${moduleCode}
`

fs.writeFileSync(outputPath, output)
