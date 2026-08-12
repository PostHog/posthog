#!/usr/bin/env node

import { build } from 'esbuild'
import { resolve } from 'node:path'

function parseEntryPoints(args: string[]): Record<string, string> {
    const entryPoints: Record<string, string> = { server: resolve(process.cwd(), 'src/index.ts') }

    for (let index = 0; index < args.length; index++) {
        if (args[index] !== '--entry') {
            throw new Error(`Unknown argument: ${args[index]}`)
        }
        const entry = args[index + 1]
        if (!entry) {
            throw new Error('--entry requires a name=path value')
        }
        const separator = entry.indexOf('=')
        if (separator <= 0 || separator === entry.length - 1) {
            throw new Error(`Invalid entry point: ${entry}`)
        }
        const name = entry.slice(0, separator)
        const source = entry.slice(separator + 1)
        entryPoints[name] = source.startsWith('.') || source.startsWith('/') ? resolve(process.cwd(), source) : source
        index++
    }

    return entryPoints
}

async function main(): Promise<void> {
    const entryPoints = parseEntryPoints(process.argv.slice(2))
    await build({
        entryPoints,
        bundle: true,
        platform: 'node',
        target: 'node24',
        format: 'esm',
        outdir: resolve(process.cwd(), 'dist'),
        outExtension: { '.js': '.mjs' },
        sourcemap: true,
        external: ['pg-native'],
        banner: {
            js: "import { createRequire as __createRequire } from 'node:module'; const require = __createRequire(import.meta.url);",
        },
    })

    console.info(`Built ${Object.keys(entryPoints).join(', ')} into dist/`)
}

main().catch((error: unknown) => {
    console.error(error instanceof Error ? error.message : String(error))
    process.exitCode = 1
})
