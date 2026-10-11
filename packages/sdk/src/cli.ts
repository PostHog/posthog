#!/usr/bin/env node
import { readFileSync, realpathSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { catalog, describeTool, searchTools } from './discovery.js'

const usage =
    'Usage: posthog-sdk --agent-help | list [--json] | search <words> [--json] | describe <method-or-tool> [--json]\n\nAgents: run npx @posthog/sdk --agent-help before starting a PostHog task.'

export function runCli(args: string[]): string {
    if (args.length === 1 && args[0] === '--agent-help') {
        return readFileSync(new URL('./agent-help.md', import.meta.url), 'utf8').trim()
    }
    const json = args.includes('--json')
    const [command, ...rest] = args.filter((value) => value !== '--json')
    if (!command || command === '--help' || command === 'help') {
        return usage
    }
    if (command === 'list') {
        return json
            ? JSON.stringify(catalog, null, 2)
            : catalog.tools.map((tool) => `${tool.method}\t${tool.title}`).join('\n')
    }
    if (command === 'search') {
        if (!rest.length) {
            throw new Error(usage)
        }
        const results = searchTools(rest.join(' '))
        return json
            ? JSON.stringify(results, null, 2)
            : results.map((tool) => `${tool.method}\t${tool.title}\t${tool.descriptionFile}`).join('\n')
    }
    if (command === 'describe' && rest.length === 1) {
        const tool = describeTool(rest[0]!)
        if (!tool) {
            throw new Error('Unknown SDK method or MCP tool name. Use posthog-sdk search to find an exported method.')
        }
        if (json) {
            return JSON.stringify(tool, null, 2)
        }
        const source = readFileSync(new URL(`../${tool.input.source}`, import.meta.url), 'utf8')
        const documentation = [
            ...new Set([tool.description, ...tool.methodDocumentation.map((layer) => layer.text)]),
        ].join('\n\n')
        return `${tool.method}\nRequired scopes: ${tool.requiredScopes.join(', ')}\nInput: ${tool.input.source}#${tool.input.name}\nOutput: ${tool.output.source}#${tool.output.name}\n\n${documentation}\n\n${source}`
    }
    throw new Error(usage)
}

if (process.argv[1] && realpathSync(process.argv[1]) === fileURLToPath(import.meta.url)) {
    try {
        process.stdout.write(`${runCli(process.argv.slice(2))}\n`)
    } catch (error) {
        console.error(error instanceof Error ? error.message : 'Operation discovery failed.')
        process.exitCode = 1
    }
}
