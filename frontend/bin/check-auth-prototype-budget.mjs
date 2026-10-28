#!/usr/bin/env node
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { authPrototypeBootBytes } from './auth-prototype-graph.mjs'

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const metaPath = path.join(frontendDir, 'auth-prototype-esbuild-meta.json')
const budgetBytes = 3_700_000

try {
    const meta = JSON.parse(fs.readFileSync(metaPath, 'utf8'))
    const { bytes, files } = authPrototypeBootBytes(meta)
    console.info(
        `Auth prototype boot: ${bytes.toLocaleString()} bytes across ${files} files (budget ${budgetBytes.toLocaleString()})`
    )
    if (bytes > budgetBytes) {
        console.error(`Auth prototype boot exceeds its ${budgetBytes.toLocaleString()} byte budget.`)
        process.exitCode = 1
    }
} catch (error) {
    console.error(`Could not check auth prototype boot size: ${error.message}`)
    process.exitCode = 1
}
