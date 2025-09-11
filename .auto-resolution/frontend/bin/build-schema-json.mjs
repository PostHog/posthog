#!/usr/bin/env node
// replaces ts-json-schema-generator -f tsconfig.json --path 'frontend/src/queries/schema.ts' --no-type-check > frontend/src/queries/schema.json
import fs from 'fs'
import stableStringify from 'safe-stable-stringify'
import tsj from 'ts-json-schema-generator'

/** @type {import('ts-json-schema-generator/dist/src/Config').Config} */
const config = {
    ...tsj.DEFAULT_CONFIG,
    path: './src/queries/schema/index.ts',
    tsconfig: 'tsconfig.json',
    discriminatorType: 'open-api',
    skipTypeCheck: true,
}

const output_path = 'src/queries/schema.json'

const schema = tsj.createGenerator(config).createSchema(config.type)
const stringify = config.sortProps ? stableStringify : JSON.stringify
const schemaString = config.minify ? stringify(schema) : stringify(schema, null, 2)

fs.writeFile(output_path, schemaString, (err) => {
    if (err) {
        throw err
    }
})
