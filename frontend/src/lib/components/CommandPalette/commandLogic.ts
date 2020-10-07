import { kea } from 'kea'

interface CommandResult {
    icon: JSX.Element
    text: string
    executor: () => void
}

type CommandResolver = (argument: string) => CommandResult[]

interface Command {
    prefixes?: string[] // command synonyms, e.g. "go to"
    resolver: CommandResolver // resolver based on arguments (prefix excluded)
}

export const commandLogic = kea({
    actions: () => ({
        registerCommand: (command: Command) => ({ command }),
    }),
    reducers: ({ actions, values }) => ({
        prefixLookupTable: [
            {} as { [commandPrefix: string]: CommandResolver[] }, // prefix '' is resolved always (e.g. Dashboard names)
            {
                [actions.registerCommand]: (_, { command }: { command: Command }) => {
                    const newLookupTable = { ...values.commands }
                    if (command.prefixes) {
                        for (const prefix of command.prefixes) {
                            newLookupTable[prefix] = [...(newLookupTable[prefix] ?? []), command.resolver]
                        }
                    } else {
                        newLookupTable[''] = [...(newLookupTable[''] ?? []), command.resolver]
                    }
                    return newLookupTable
                },
            },
        ],
    }),
})
