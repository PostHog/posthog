import type { CommandTree } from '@/core/command'

import api from './api'
import auth from './auth'
import ci from './ci'
import commands from './commands'
import config from './config'
import endpoints from './endpoints'
import errorTracking from './error-tracking'
import { LEGACY_COMMANDS } from './legacy'
import mcp from './mcp'
import query from './query'
import schema from './schema'
import setup from './setup'
import skills from './skills'
import upgrade from './upgrade'

export const COMMANDS: CommandTree = {
    setup,
    auth,
    ci,
    query,
    api,
    skills,
    mcp,
    'error-tracking': errorTracking,
    endpoints,
    schema,
    config,
    commands,
    upgrade,
    ...LEGACY_COMMANDS,
}
