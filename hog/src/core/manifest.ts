import { optionFlags, type CommandTree, type OptionSpec } from './command'
import { GLOBAL_OPTIONS } from './globals'
import { kebabCase } from './text'

interface OptionEntry {
    flags: string
    description: string
    takesValue: boolean
    choices?: readonly string[]
    repeatable?: boolean
    env?: readonly string[]
    config?: string
}

export interface ManifestEntry {
    name: string
    description: string
    available: boolean
    arguments?: { name: string; description: string; required: boolean; variadic: boolean; stdin: boolean }[]
    options?: OptionEntry[]
    scopes?: readonly string[]
    examples?: readonly string[]
    // The posthog-cli command to run instead, for commands hog doesn't have yet.
    use?: string
}

function describeOptions(options: Readonly<Record<string, OptionSpec>>): OptionEntry[] {
    return Object.entries(options).map(([name, spec]) => ({
        flags: optionFlags(name, spec),
        description: spec.description,
        takesValue: spec.type === 'string',
        choices: spec.type === 'string' ? spec.choices : undefined,
        repeatable: spec.type === 'string' && spec.multiple === true ? true : undefined,
        env: spec.env,
        config: spec.config,
    }))
}

export function describeCommands(tree: CommandTree, prefix = ''): ManifestEntry[] {
    return Object.entries(tree).flatMap(([name, node]): ManifestEntry[] => {
        const path = prefix ? `${prefix} ${name}` : name
        switch (node.kind) {
            case 'group':
                return describeCommands(node.commands, path)
            case 'legacy':
                return [{ name: path, description: node.description, available: false, use: node.use }]
            case 'command':
                return [
                    {
                        name: path,
                        description: node.description,
                        available: true,
                        arguments: Object.entries(node.args ?? {}).map(([argName, spec]) => ({
                            name: kebabCase(argName),
                            description: spec.description,
                            required: spec.optional !== true,
                            variadic: spec.variadic === true,
                            stdin: spec.stdin === true,
                        })),
                        options: describeOptions(node.options ?? {}),
                        scopes: node.scopes ?? [],
                        examples: node.examples ?? [],
                    },
                ]
        }
    })
}

export function describeAliases(tree: CommandTree, prefix = ''): Record<string, string> {
    return Object.fromEntries(
        Object.entries(tree).flatMap(([name, node]) => {
            if (node.kind !== 'group') {
                return []
            }
            const path = prefix ? `${prefix} ${name}` : name
            const own = (node.aliases ?? []).map((alias) => [prefix ? `${prefix} ${alias}` : alias, path])
            return [...own, ...Object.entries(describeAliases(node.commands, path))]
        })
    )
}

export function describeGlobalOptions(): OptionEntry[] {
    return describeOptions(GLOBAL_OPTIONS)
}
