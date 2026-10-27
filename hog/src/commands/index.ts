import query from '@/commands/query'
import type { CommandTree } from '@/core/command'

import commands from './commands'
import { LEGACY_COMMANDS } from './legacy'

export const COMMANDS: CommandTree = {
    query,
    commands,
    ...LEGACY_COMMANDS,
}
