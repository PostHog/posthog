import { execFileSync } from 'node:child_process'
import fs from 'node:fs/promises'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
execFileSync(
    process.execPath,
    [require.resolve('typescript/bin/tsc'), '-p', fileURLToPath(new URL('../tsconfig.json', import.meta.url))],
    { stdio: 'inherit' }
)
await fs.copyFile(
    new URL('../src/generated/handlers.mjs', import.meta.url),
    new URL('../dist/generated/handlers.mjs', import.meta.url)
)
await fs.copyFile(
    new URL('../src/generated/handlers.d.mts', import.meta.url),
    new URL('../dist/generated/handlers.d.mts', import.meta.url)
)
