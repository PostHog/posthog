import { kea, useActions, useValues } from 'kea'
import { useCallback, useEffect } from 'react'
import { commandLogicType } from 'types/lib/components/CommandPalette/commandLogicType'

export type CommandExecutor = (utils: Utils) => void

export interface CommandResult {
    icon: any // any, because Ant Design icons are some weird ForwardRefExoticComponent type
    text: string
    executor: CommandExecutor
}

export interface Utils {
    push?: (url: string) => void // kea-router URL push
}

export type CommandResolver = (argument?: string) => CommandResult[]

export interface Command {
    key: string // Unique command identification key
    prefixes?: string[] // Command synonyms, e.g. "go to". Prefix-less case is dynamic base command (e.g. Dashboard)
    resolver: CommandResolver // Resolver based on arguments (prefix excluded)
}

export type CommandRegistrations = {
    [commandKey: string]: Command
}

export type RegExpResolverPairs = [RegExp | null, CommandResolver][]

export const commandLogic = kea<commandLogicType<Command, CommandRegistrations>>({
    actions: {
        registerCommand: (command: Command) => ({ command }),
        deregisterCommand: (commandKey: string) => ({ commandKey }),
    },
    reducers: {
        commandRegistrations: [
            {} as CommandRegistrations,
            {
                registerCommand: (commands, { command }) => {
                    return { ...commands, [command.key]: command }
                },
                deregisterCommand: (commands, { commandKey }) => {
                    const cleanedCommands = { ...commands }
                    delete cleanedCommands[commandKey]
                    return cleanedCommands
                },
            },
        ],
    },
    selectors: {
        regexpResolverPairs: [
            (selectors) => [selectors.commandRegistrations],
            (commandRegistrations) => {
                const array: RegExpResolverPairs = []
                for (const command of Object.values(commandRegistrations)) {
                    if (command.prefixes)
                        array.push([
                            new RegExp(`^\\s*(${command.prefixes.join('|')})(?:\\s+(.*)|$)`, 'i'),
                            command.resolver,
                        ])
                    else array.push([null, command.resolver])
                }
                return array
            },
        ],
    },
})

export function useCommands(commands: Command[]): void {
    const { registerCommand, deregisterCommand } = useActions(commandLogic)
    useEffect(() => {
        for (const command of commands) {
            console.log('trying to register command', command)
            registerCommand(command)
        }
        return () => {
            for (const command of commands) deregisterCommand(command.key)
        }
    }, [commands])
}

export function useCommandsSearch(maximumResults: number = 5): (argument: string) => CommandResult[] {
    const { regexpResolverPairs } = useValues(commandLogic)

    return useCallback(
        (argument: string): CommandResult[] => {
            const results: CommandResult[] = []
            for (const [regexp, resolver] of regexpResolverPairs) {
                if (results.length >= maximumResults) break
                if (regexp) {
                    // Prefix-based case
                    const match = argument.match(regexp)
                    if (match && match[1]) results.push(...resolver(match[2]))
                } else {
                    // Raw argument command
                    results.push(...resolver(argument))
                }
            }
            console.log(results.slice(0, 10))
            return results.slice(0, 10)
        },
        [regexpResolverPairs]
    )
}
