import { kea, useActions } from 'kea'
import { useEffect } from 'react'

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
    prefixes?: string[] // Command synonyms, e.g. "go to". Prefix-less case is empty string '' (e.g. Dashboard names)
    resolver: CommandResolver // Resolver based on arguments (prefix excluded)
}

export type CommandRegistrations = {
    [commandKey: string]: Command
}

export type CommandPrefixLUT = {
    [prefix: string]: CommandResolver[]
}

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
        prefixLookupTable: [
            (selectors) => [selectors.commandRegistrations],
            (commandRegistrations: CommandRegistrations) => {
                const newLookupTable: CommandPrefixLUT = {}
                for (const command of Object.values(commandRegistrations)) {
                    if (command.prefixes) {
                        for (const prefix of command.prefixes) {
                            newLookupTable[prefix] = [...(newLookupTable[prefix] ?? []), command.resolver]
                        }
                    } else {
                        newLookupTable[''] = [...(newLookupTable[''] ?? []), command.resolver]
                    }
                }
                return newLookupTable
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
