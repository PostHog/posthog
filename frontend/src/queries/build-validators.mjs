#!/usr/bin/env node
import Ajv from 'ajv'
import standaloneCode from 'ajv/dist/standalone/index.js'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// Load the schema
const schema = JSON.parse(fs.readFileSync(path.join(__dirname, 'schema.json'), 'utf-8'))

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
// This file is committed to the repository for CI/CD compatibility
// To regenerate: pnpm schema:build (after modifying schema types)
${moduleCode}
`

fs.writeFileSync(path.join(__dirname, 'validators.js'), output)
