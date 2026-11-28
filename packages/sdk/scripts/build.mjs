import { execFileSync } from 'node:child_process'
import fs from 'node:fs/promises'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
const mcp = new URL('../../../services/mcp/', import.meta.url)
const mcpRequire = createRequire(new URL('package.json', mcp))
execFileSync(process.execPath, ['--import', mcpRequire.resolve('tsx'), 'scripts/build-cli-library.ts'], {
    cwd: mcp,
    stdio: 'inherit',
})
await fs.rm(new URL('../dist/', import.meta.url), { recursive: true, force: true })
execFileSync(
    process.execPath,
    [require.resolve('typescript/bin/tsc'), '-p', fileURLToPath(new URL('../tsconfig.json', import.meta.url))],
    { stdio: 'inherit' }
)
await fs.copyFile(new URL('dist/cli-library.mjs', mcp), new URL('../dist/runtime/tool-library.mjs', import.meta.url))
