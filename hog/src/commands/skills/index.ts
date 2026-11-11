import { defineGroup } from '@/core/command'

import add from './add'
import guide from './guide'
import list from './list'
import read from './read'

export default defineGroup({
    description: 'List, read and add PostHog agent skills',
    commands: { list, read, add },
    guide,
})
