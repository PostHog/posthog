#!/usr/bin/env node
import { existsSync, readFileSync, realpathSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { domains } from './discovery.js'

const usage =
    'Usage: posthog-sdk --agent-help\n\nSearch api-index.tsv and src/generated/api.ts with grep or rg. Run --agent-help for available domains, absolute file locations, and workflow guidance.'

export function runCli(args: string[]): string {
    if (args.length === 1 && args[0] === '--agent-help') {
        const paths = {
            API: fileURLToPath(new URL('../src/generated/api.ts', import.meta.url)),
            INDEX: fileURLToPath(new URL('../api-index.tsv', import.meta.url)),
            DOMAINS: fileURLToPath(new URL('../domains.tsv', import.meta.url)),
        }
        let guide = readFileSync(new URL('./agent-help.md', import.meta.url), 'utf8').trim()
        for (const [name, path] of Object.entries(paths)) {
            guide = guide.replaceAll(`__SDK_${name}_PATH__`, () => path)
            guide = guide.replaceAll(`__SDK_${name}_SHELL__`, () => `'${path.replaceAll("'", "'\\''")}'`)
        }
        return guide.replaceAll('__SDK_DOMAIN_LIST__', () =>
            domains
                .map(({ domain, methods }) => `- \`${domain}\`: ${methods} method${methods === 1 ? '' : 's'}`)
                .join('\n')
        )
    }
    const [command] = args
    if (!command || command === '--help' || command === 'help') {
        return usage
    }
    throw new Error(usage)
}

if (
    process.argv[1] &&
    existsSync(process.argv[1]) &&
    realpathSync(process.argv[1]) === fileURLToPath(import.meta.url)
) {
    try {
        process.stdout.write(`${runCli(process.argv.slice(2))}\n`)
    } catch (error) {
        console.error(error instanceof Error ? error.message : 'Operation discovery failed.')
        process.exitCode = 1
    }
}
