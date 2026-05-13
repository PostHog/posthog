#!/usr/bin/env node

import { spawnSync } from 'node:child_process'
import { createRequire } from 'node:module'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
const currentDir = dirname(fileURLToPath(import.meta.url))
const tsxCli = require.resolve('tsx/cli')
const entrypoint = resolve(currentDir, '../src/index.ts')

const result = spawnSync(process.execPath, [tsxCli, entrypoint, ...process.argv.slice(2)], {
  stdio: 'inherit',
})

if (result.error) {
  console.error(result.error.message)
  process.exit(1)
}

process.exit(result.status ?? 1)
