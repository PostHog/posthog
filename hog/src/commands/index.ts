import query from '@/commands/query'
import type { CommandTree } from '@/core/command'

import commands from './commands'
import { LEGACY_COMMANDS } from './legacy'
import login from './login'

export const COMMANDS: CommandTree = {
    login,
    query,
    commands,
    ...LEGACY_COMMANDS,
}
