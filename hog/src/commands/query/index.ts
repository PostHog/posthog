import { defineGroup, defineLegacy } from '@/core/command'

import check from './check'
import run from './run'

export default defineGroup({
    description: 'Run and check HogQL queries against your project',
    commands: {
        run,
        check,
        editor: defineLegacy({ description: 'Open the interactive query editor', use: 'posthog-cli exp query editor' }),
    },
})
