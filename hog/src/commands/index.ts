import type { CommandTree } from '../core/command'
import commands from './commands'
import { LEGACY_COMMANDS } from './legacy'
import query from './query'

export const COMMANDS: CommandTree = {
    query,
    commands,
    ...LEGACY_COMMANDS,
}
