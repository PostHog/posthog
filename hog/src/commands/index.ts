import type { CommandTree } from '@/core/command'

import auth from './auth'
import commands from './commands'
import config from './config'
import errorTracking from './error-tracking'
import { LEGACY_COMMANDS } from './legacy'
import query from './query'

export const COMMANDS: CommandTree = {
    auth,
    query,
    'error-tracking': errorTracking,
    config,
    commands,
    ...LEGACY_COMMANDS,
}
