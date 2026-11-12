import { defineGroup, defineLegacy } from '@/core/command'

import access from './access'
import call from './call'
import groups from './groups'
import info from './info'
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
        'agents-md': defineLegacy({
            description: 'Install the PostHog steering snippet in AGENTS.md',
            use: 'posthog-cli api agents-md',
        }),
    },
})
