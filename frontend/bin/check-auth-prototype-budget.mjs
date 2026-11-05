#!/usr/bin/env node
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { authPrototypeBootShare } from './auth-prototype-graph.mjs'

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
// Written by the eager graph check in build:with-report, which measures both roots from the same build.
const eagerGraphReportPath = path.join(frontendDir, 'eager-graph-report.json')
// The separate entry only earns its upkeep while it boots clearly smaller than the login page it replaces.
const maxShareOfCurrentLoginBoot = 0.9

try {
    const { bytes, files, currentBytes, share } = authPrototypeBootShare(
        JSON.parse(fs.readFileSync(eagerGraphReportPath, 'utf8'))
    )
    console.info(
        `Auth prototype boot: ${bytes.toLocaleString()} bytes across ${files} files, ` +
            `${Math.round(share * 100)}% of the current logged-out boot (${currentBytes.toLocaleString()} bytes)`
    )
    if (share > maxShareOfCurrentLoginBoot) {
        // A warning, not a failure: a perf win on the main boot must not block its own PR.
        console.info(
            `::warning title=Auth prototype boot::The auth prototype boot is ${Math.round(share * 100)}% of the ` +
                `current logged-out boot, over ${maxShareOfCurrentLoginBoot * 100}%. ` +
                `Make its imports smaller, or decide whether the separate entry is still worth keeping.`
        )
    }
} catch (error) {
    console.error(`Could not check auth prototype boot size: ${error.message}`)
    process.exitCode = 1
}
