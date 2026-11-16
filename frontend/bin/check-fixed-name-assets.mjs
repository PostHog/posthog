#!/usr/bin/env node
// Fails when dist/ holds fixed-name code that fixed-name-assets-allowlist.mjs does not list, or the list has a stale entry.
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { FIXED_NAME_ASSET_GROUPS } from './fixed-name-assets-allowlist.mjs'
import { checkFixedNameFiles } from './fixedNameAssets.mjs'

const distDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'dist')

function listDistPaths() {
    return fs
        .readdirSync(distDir, { recursive: true, withFileTypes: true })
        .filter((entry) => entry.isFile())
        .map((entry) => path.relative(distDir, path.join(entry.parentPath, entry.name)).split(path.sep).join('/'))
}

function printUnlisted(unlisted) {
    console.error(`\nFixed-name code in frontend/dist/ that the allowlist does not cover:`)
    for (const distPath of unlisted) {
        console.error(`  ${distPath}`)
    }
    console.error(
        `\nThe CDN overwrites a file without a content hash in place, so a tab that stays open loads the new` +
            `\nversion of this file with its old JS. Give the file a content-hashed name (Name-HASH.js, as esbuild` +
            `\nentryNames do) and load it by that name. Only when the fixed name is a public URL contract that` +
            `\nother sites load, add it to frontend/bin/fixed-name-assets-allowlist.mjs with the reason.`
    )
}

function printStale(stale) {
    console.error(`\nAllowlist entries in frontend/bin/fixed-name-assets-allowlist.mjs that match no file in dist/:`)
    for (const entry of stale) {
        console.error(`  ${entry}`)
    }
    console.error(`\nRemove these entries, so the allowlist cannot cover a new file by the same name later.`)
}

function main() {
    if (!fs.existsSync(distDir)) {
        console.error(`No ${distDir}. Run \`pnpm --filter=@posthog/frontend build\` first.`)
        process.exit(1)
    }
    const allowlistEntries = FIXED_NAME_ASSET_GROUPS.flatMap((group) => group.entries)
    const { fixedNamePaths, unlisted, stale } = checkFixedNameFiles(listDistPaths(), allowlistEntries)
    if (unlisted.length > 0) {
        printUnlisted(unlisted)
    }
    if (stale.length > 0) {
        printStale(stale)
    }
    if (unlisted.length > 0 || stale.length > 0) {
        process.exit(1)
    }
    console.info(`Fixed-name assets OK: ${fixedNamePaths.length} fixed-name code files, all on the allowlist.`)
}

main()
