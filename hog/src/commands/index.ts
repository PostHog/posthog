import type { CommandTree } from '@/core/command'

import api from './api'
import auth from './auth'
import ci from './ci'
import commands from './commands'
import config from './config'
import endpoints from './endpoints'
import errorTracking from './error-tracking'
import feedback from './feedback'
import mcp from './mcp'
import query from './query'
import schema from './schema'
import setup from './setup'
import skills from './skills'
import stack from './stack'
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
    stack,
    schema,
    config,
    commands,
    upgrade,
    feedback,
}
