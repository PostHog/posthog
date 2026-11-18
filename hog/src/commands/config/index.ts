import { defineGroup } from '@/core/command'

import check from './check'
import schema from './schema'

export default defineGroup({
    description: 'Check posthog.json, the project settings file hog reads',
    commands: { check, schema },
})
