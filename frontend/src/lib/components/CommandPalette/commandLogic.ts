import { kea } from 'kea'

interface CommandResult {
    icon: JSX.Element
    text: string
    executor: () => void
}

type CommandResolver = (argument: string) => CommandResult[]

type StaticCommand = (commandSynonyms: string[]) => CommandResolver
type DynamicCommand = (resolver: CommandResolver) => CommandResult
