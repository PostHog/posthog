#!/usr/bin/env node
import { spawnSync } from 'child_process'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const scriptPath = fileURLToPath(import.meta.url)
const frontendDir = path.resolve(path.dirname(scriptPath), '..')
const repoRoot = path.resolve(frontendDir, '..')
const localKeaTypegenBin = path.resolve(
    frontendDir,
    'node_modules',
    '.bin',
    process.platform === 'win32' ? 'kea-typegen.cmd' : 'kea-typegen'
)

const { fileArg, passthroughArgs } = parseArgs(process.argv.slice(2))

if (!fileArg) {
    console.error('Usage: pnpm --filter=@posthog/frontend typegen:file <logic-file> [kea-typegen options]')
    process.exit(1)
}

const resolvedFile = resolveFile(fileArg)

if (!resolvedFile) {
    console.error(`Could not find logic file: ${fileArg}`)
    console.error('Checked paths relative to the current directory, pnpm INIT_CWD, frontend/, and the repo root.')
    process.exit(1)
}

const nodeOptions = process.env.NODE_OPTIONS?.includes('--max-old-space-size')
    ? process.env.NODE_OPTIONS
    : [process.env.NODE_OPTIONS, '--max-old-space-size=4096'].filter(Boolean).join(' ')

const result = spawnSync(
    fs.existsSync(localKeaTypegenBin) ? localKeaTypegenBin : 'kea-typegen',
    ['write', '--show-ts-errors', '--file', resolvedFile, ...passthroughArgs],
    {
        cwd: repoRoot,
        env: {
            ...process.env,
            NODE_OPTIONS: nodeOptions,
        },
        stdio: 'inherit',
    }
)

if (result.error) {
    console.error(`Failed to run kea-typegen: ${result.error.message}`)
    process.exit(1)
}

process.exit(result.status ?? 1)

function parseArgs(args) {
    let fileArg
    const passthroughArgs = []

    for (let index = 0; index < args.length; index++) {
        const arg = args[index]

        if (arg === '--file' || arg === '-f') {
            fileArg = args[index + 1]
            index += 1
            continue
        }

        if (arg.startsWith('--file=')) {
            fileArg = arg.slice('--file='.length)
            continue
        }

        if (arg.startsWith('-f=')) {
            fileArg = arg.slice('-f='.length)
            continue
        }

        if (!fileArg && !arg.startsWith('-')) {
            fileArg = arg
            continue
        }

        passthroughArgs.push(arg)
    }

    return { fileArg, passthroughArgs }
}

function resolveFile(filePath) {
    const candidates = (
        path.isAbsolute(filePath)
            ? [filePath]
            : [
                  path.resolve(process.cwd(), filePath),
                  process.env.INIT_CWD && path.resolve(process.env.INIT_CWD, filePath),
                  path.resolve(frontendDir, filePath),
                  path.resolve(repoRoot, filePath),
              ]
    ).filter(Boolean)

    for (const candidate of candidates) {
        if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) {
            return candidate
        }
    }

    return undefined
}
