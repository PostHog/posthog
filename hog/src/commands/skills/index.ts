import { defineGroup } from '@/core/command'

import add from './add'
import guide from './guide'
import list from './list'
import read from './read'
import search from './search'

export default defineGroup({
    description: 'List, search, read and add PostHog agent skills',
    commands: { list, search, read, add },
    guide,
})
