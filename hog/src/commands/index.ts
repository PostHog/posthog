import type { CommandTree } from '@/core/command'

import auth from './auth'
import commands from './commands'
import { LEGACY_COMMANDS } from './legacy'
import query from './query'

export const COMMANDS: CommandTree = {
    auth,
    query,
    commands,
    ...LEGACY_COMMANDS,
}
