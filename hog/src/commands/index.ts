import type { CommandTree } from '@/core/command'

import api from './api'
import auth from './auth'
import ci from './ci'
import commands from './commands'
import config from './config'
import endpoints from './endpoints'
import errorTracking from './error-tracking'
import learn from './learn'
import { LEGACY_COMMANDS } from './legacy'
import query from './query'
import schema from './schema'
import setup from './setup'

export const COMMANDS: CommandTree = {
    setup,
    auth,
    ci,
    query,
    api,
    learn,
    'error-tracking': errorTracking,
    endpoints,
    schema,
    config,
    commands,
    ...LEGACY_COMMANDS,
}
