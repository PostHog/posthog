import { defineGroup } from '@/core/command'

import add from './add'

export default defineGroup({
    description: "Connect PostHog's MCP server to your agent",
    commands: { add },
})
