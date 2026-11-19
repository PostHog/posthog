import { defineGroup } from '@/core/command'

import access from './access'
import call from './call'
import groups from './groups'
import info from './info'
import refresh from './refresh'
import schema from './schema'
import search from './search'
import tools from './tools'

export default defineGroup({
    description: 'Browse and call the PostHog API through the tools the PostHog MCP server offers',
    commands: {
        groups,
        tools,
        search,
        info,
        schema,
        call,
        access,
        refresh,
    },
})
