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
    extraTags: ['schemaEnum'],
}

const output_path = 'src/queries/schema.json'

const schema = tsj.createGenerator(config).createSchema(config.type)

// The generator writes a one-member enum as `const`, which Python gets as a `Literal` root model.
// Tag a TS enum `@schemaEnum` to keep its `enum` list, so Python gets a `StrEnum` at any size.
for (const definition of Object.values(schema.definitions ?? {})) {
    if (definition.schemaEnum !== undefined) {
        if ('const' in definition) {
            definition.enum = [definition.const]
            delete definition.const
        }
        delete definition.schemaEnum
    }
}

const stringify = config.sortProps ? stableStringify : JSON.stringify
const schemaString = config.minify ? stringify(schema) : stringify(schema, null, 2)

fs.writeFile(output_path, schemaString, (err) => {
    if (err) {
        throw err
    }
})
