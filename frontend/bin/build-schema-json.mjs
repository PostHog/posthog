#!/usr/bin/env node
import fs from 'fs'
// replaces ts-json-schema-generator -f tsconfig.json --path 'common/query-frontend/src/schema/index.ts' --no-type-check > common/query-frontend/src/schema.json
import stableStringify from 'safe-stable-stringify'
import tsj from 'ts-json-schema-generator'

/** @type {import('ts-json-schema-generator/dist/src/Config').Config} */
const config = {
    ...tsj.DEFAULT_CONFIG,
    path: '../common/query-frontend/src/schema/index.ts',
    tsconfig: 'tsconfig.json',
    discriminatorType: 'open-api',
    skipTypeCheck: true,
}

const output_path = '../common/query-frontend/src/schema.json'

const schema = tsj.createGenerator(config).createSchema(config.type)
const stringify = config.sortProps ? stableStringify : JSON.stringify
const schemaString = config.minify ? stringify(schema) : stringify(schema, null, 2)

fs.writeFile(output_path, schemaString, (err) => {
    if (err) {
        throw err
    }
})
