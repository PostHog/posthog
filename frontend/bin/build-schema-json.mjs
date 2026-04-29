#!/usr/bin/env node
import fs from 'fs'
// replaces ts-json-schema-generator -f tsconfig.json --path 'frontend/src/queries/schema.ts' --no-type-check > frontend/src/queries/schema.json
import stableStringify from 'safe-stable-stringify'
import tsj from 'ts-json-schema-generator'

/** @type {import('ts-json-schema-generator/dist/src/Config').Config} */
const config = {
    ...tsj.DEFAULT_CONFIG,
    path: './src/queries/schema/index.ts',
    tsconfig: 'tsconfig.json',
    discriminatorType: 'open-api',
    skipTypeCheck: true,
    // Pass custom JSDoc tags through into the generated JSON Schema as field-level
    // properties. Used by the guest-mode query rescoper to identify which query fields
    // a viewer-level user may override. See posthog/rbac/guest_query_scope.py.
    extraTags: ['guestOverridable'],
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
