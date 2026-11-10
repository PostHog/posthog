// Prints, one per line, what the pinned schemas are cut to, read from the Node packages' sources and tests
// with node-common's schema-check derivation (build node-common first):
//   postgres-tables  the Django-owned Postgres tables the packages' SQL names
//   identifiers      every lowercase identifier in the packages, for cut_clickhouse_schema.py
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')
const require = createRequire(import.meta.url)
const derive = require(path.join(root, 'nodejs/packages/common/dist/schema-check/derive-requirements.js'))

const sourceRoots = [
    'nodejs/packages/common',
    'nodejs/packages/hog-engine',
    'nodejs/packages/replay-storage',
    'ingestion/node/packages/common',
    'ingestion/node/packages/ingestion',
    'ingestion/node/packages/ai-research',
].flatMap((dir) => ['src', 'tests'].map((sub) => path.join(root, dir, sub)))

let names
switch (process.argv[2]) {
    case 'postgres-tables': {
        const owners = derive.collectTableOwners(derive.findDjangoApps(root))
        names = [...derive.collectNodeSqlTables(sourceRoots, true).postgres].filter((table) => owners.has(table))
        break
    }
    case 'identifiers':
        names = [...derive.collectNodeIdentifiers(sourceRoots, true)]
        break
    default:
        console.error('usage: node_schema_names.mjs postgres-tables|identifiers')
        process.exit(2)
}
for (const name of names.sort()) {
    console.log(name)
}
