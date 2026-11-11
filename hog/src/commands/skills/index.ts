import { defineGroup } from '@/core/command'

import add from './add'
import guide from './guide'
import list from './list'

export default defineGroup({
    description: 'List PostHog agent skills, and add them to this repository',
    commands: { list, add },
    guide,
})
