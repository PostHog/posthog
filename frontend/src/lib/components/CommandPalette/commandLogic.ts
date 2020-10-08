import { kea, useActions, useValues } from 'kea'
import { useCallback, useEffect } from 'react'
import { commandLogicType } from 'types/lib/components/CommandPalette/commandLogicType'
import Fuse from 'fuse.js'

export type CommandExecutor = (utils: Utils) => void

export interface CommandResult {
    key: string // string for sorting results according to typed text
    icon: any // any, because Ant Design icons are some weird ForwardRefExoticComponent type
    prefixApplied?: string
    synonyms?: string[]
    display: string
    executor: CommandExecutor
}

export interface DefinedUtils {
    push: (url: string) => void // kea-router URL push
}

export interface CustomUtils {
    [customUtil: string]: (...args: any) => any
}

export type Utils = CustomUtils & DefinedUtils

export type CommandResolver = (argument?: string, prefixApplied?: string) => CommandResult[]

export interface Command {
    key: string // Unique command identification key
    prefixes?: string[] // Command synonyms, e.g. "go to". Prefix-less case is dynamic base command (e.g. Dashboard)
    resolver: CommandResolver // Resolver based on arguments (prefix excluded)
    utils: CustomUtils
}

export type CommandRegistrations = {
    [commandKey: string]: Command
}

export type RegExpCommandPairs = [RegExp | null, Command][]
export interface CommandSearchEntry {
    prefix: string
    command: Command
}

const RESULTS_MAX = 8

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
        regexpCommandPairs: [
            (selectors) => [selectors.commandRegistrations],
            (commandRegistrations: CommandRegistrations) => {
                const array: RegExpCommandPairs = []
                for (const command of Object.values(commandRegistrations)) {
                    if (command.prefixes)
                        array.push([new RegExp(`^\\s*(${command.prefixes.join('|')})(?:\\s+(.*)|$)`, 'i'), command])
                    else array.push([null, command])
                }
                return array
            },
        ],
        commandSearchEntries: [
            (selectors) => [selectors.commandRegistrations],
            (commandRegistrations: CommandRegistrations) => {
                const array: CommandSearchEntry[] = []
                for (const command of Object.values(commandRegistrations)) {
                    if (command.prefixes) for (const prefix of command.prefixes) array.push({ prefix, command })
                }
                return array
            },
        ],
        fuse: [
            (selectors) => [selectors.commandSearchEntries],
            (commandSearchEntries: CommandSearchEntry[]) => {
                return new Fuse(commandSearchEntries, { keys: ['prefix'] })
            },
        ],
    },
})

export function useCommands(commands: Command[]): void {
    const { registerCommand, deregisterCommand } = useActions(commandLogic)
    useEffect(() => {
        for (const command of commands) {
            registerCommand(command)
        }
        return () => {
            for (const command of commands) deregisterCommand(command.key)
        }
    }, [commands])
}

/*function resolveCommand(command: Command, resultsArray: CommandResult[], argument?: string, prefixApplied?: string): CommandResult[] {
    return resultsArray.push(...command.resolver(argument, prefixApplied).map(result => {
        result.command = command
        return result
    }))
}*/

export function useCommandsSearch(): (argument: string) => CommandResult[] {
    const { regexpCommandPairs } = useValues(commandLogic)

    return useCallback(
        (argument: string): CommandResult[] => {
            const directResults: CommandResult[] = []
            const prefixedResults: CommandResult[] = []

            for (const [regexp, command] of regexpCommandPairs) {
                if (directResults.length + prefixedResults.length >= RESULTS_MAX) break
                if (regexp) {
                    const match = argument.match(regexp)
                    if (match && match[1]) {
                        prefixedResults.push(...command.resolver(match[2], match[1]))
                    }
                }
                directResults.push(...command.resolver(argument))
            }
            const fuse = new Fuse(directResults.concat(prefixedResults).slice(0, RESULTS_MAX), { keys: ['key'] })
            return fuse.search(argument).map((result) => result.item)
        },
        [regexpCommandPairs]
    )
}
