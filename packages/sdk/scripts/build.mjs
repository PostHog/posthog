import { execFileSync } from 'node:child_process'
import fs from 'node:fs/promises'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'

import { SdkAgentHelp } from '../../../services/mcp/scripts/lib/sdk-agent-help.mjs'

const require = createRequire(import.meta.url)
await fs.rm(new URL('../dist/', import.meta.url), { recursive: true, force: true })
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
const { operations } = await import('../dist/discovery.js')
const definitions = JSON.parse(
    await fs.readFile(new URL('../../../services/mcp/schema/tool-definitions-all.json', import.meta.url), 'utf8')
)
const help = new SdkAgentHelp(
    operations.map(({ toolName }) => ({ name: toolName, category: definitions[toolName].category }))
)
await fs.writeFile(new URL('../dist/agent-help.md', import.meta.url), `${help.render()}\n`)
