import { defineGroup } from '@/core/command'

import add from './add'
import list from './list'

export default defineGroup({
    description: 'Add PostHog agent skills to this repository',
    commands: { list, add },
})
