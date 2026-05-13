#!/usr/bin/env node

import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const currentDir = dirname(fileURLToPath(import.meta.url))
const entrypoint = resolve(currentDir, '../dist/index.js')

if (!existsSync(entrypoint)) {
  console.error('Built CLI not found. Run: pnpm build')
  process.exit(1)
}

const result = spawnSync(process.execPath, [entrypoint, ...process.argv.slice(2)], {
  stdio: 'inherit',
})

if (result.error) {
  console.error(result.error.message)
  process.exit(1)
}

process.exit(result.status ?? 1)
