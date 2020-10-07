import { kea, useActions, useValues } from 'kea'
import { useCallback, useEffect } from 'react'

export interface CommandResult {
    icon: any // any, because Ant Design icons are some weird ForwardRefExoticComponent type
    text: string
    executor: (utils: Utils) => void
}

export interface Utils {
    pushUrl?: (url: string) => void // kea-router URL push
}

export type CommandResolver = (argument: string) => CommandResult[]

export interface Command {
    key: string // Unique command identification key
    prefixes?: string[] // Command synonyms, e.g. "go to". Prefix-less case is dynamic base command (e.g. Dashboard)
    resolver: CommandResolver // Resolver based on arguments (prefix excluded)
}

export type CommandRegistrations = {
    [commandKey: string]: Command
}

export type CommandPrefixLUT = {
    [prefix: string]: CommandResolver[]
}

export type RegExpResolverPairs = [RegExp | null, CommandResolver][]

export const commandLogic = kea({
    actions: () => ({
        registerCommand: (command: Command) => ({ command }),
        deregisterCommand: (commandKey: string) => ({ commandKey }),
    }),
    reducers: ({ actions }) => ({
        commandRegistrations: [
            {} as CommandRegistrations,
            {
                [actions.registerCommand]: (commands: CommandRegistrations, { command }: { command: Command }) => {
                    return { ...commands, [command.key]: command }
                },
            },
            {
                [actions.deregisterCommand]: (
                    commands: CommandRegistrations,
                    { commandKey }: { commandKey: string }
                ) => {
                    const cleanedCommands = { ...commands }
                    delete cleanedCommands[commandKey]
                    return
                },
            },
        ],
    }),
    selectors: () => ({
        regexpResolverPairs: [
            (selectors) => [selectors.commandRegistrations],
            (commandRegistrations: CommandRegistrations) => {
                const array: RegExpResolverPairs = []
                for (const command of Object.values(commandRegistrations)) {
                    if (command.prefixes)
                        array.push([
                            new RegExp(`^\\s*(${command.prefixes.join('|')})(?:\\s+(.*)|$)`, 'i'),
                            command.resolver,
                        ])
                    else array.push([null, command.resolver])
                }
            },
        ],
    }),
})

export function useCommands(commands: Command[]): void {
    const { registerCommand, deregisterCommand } = useActions(commandLogic)

    useEffect(() => {
        for (const command of commands) registerCommand(command)
        return () => {
            for (const command of commands) deregisterCommand(command.key)
        }
    }, [commands])
}

export function useCommandsSearch(prefixLookupTable: CommandPrefixLUT): (argument: string) => CommandResult[] {
    const { regexpResolverPairs } = useValues(commandLogic)

    return useCallback(
        (argument: string): CommandResult[] => {
            const results: CommandResult[] = []
            for (const [regexp, command] of regexpResolverPairs) {
                if (regexp) {
                    // prefix-based case
                    const match = argument.match(regexp)
                    if (match && match[1]) results.push(...command.resolver(match[2]))
                } else {
                    // raw argument command
                    results.push(...command.resolver(argument))
                }
            }
            return results
        },
        [prefixLookupTable]
    )
}
