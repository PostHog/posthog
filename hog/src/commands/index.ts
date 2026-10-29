import type { CommandTree } from '@/core/command'

import api from './api'
import auth from './auth'
import commands from './commands'
import config from './config'
import endpoints from './endpoints'
import errorTracking from './error-tracking'
import { LEGACY_COMMANDS } from './legacy'
import query from './query'
import schema from './schema'

export const COMMANDS: CommandTree = {
    auth,
    query,
    api,
    'error-tracking': errorTracking,
    endpoints,
    schema,
    config,
    commands,
    ...LEGACY_COMMANDS,
}
